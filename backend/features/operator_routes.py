# =============================================================================
# backend/features/operators/operator_routes.py
# =============================================================================
# Employee PINs: Toast employees sign their work on a shared login.
#
# We keep only the people an admin gave a PIN (employee_pins: Toast employee
# GUID, name as last seen, hashed PIN). The Toast employee list itself is read
# live from Toast when needed and never stored. See core/operators.py.
#
# Sign-in (any signed-in user; the location is the login's own, admins may pass
# location_id):
#   GET     /api/operator-session                current_operator_session
#   GET     /api/operator-sign-in/people         sign_in_people
#           The employees clocked in at this location on Toast (has_pin tells
#           who can sign in). When Toast cannot be asked: everyone with a PIN.
#   POST    /api/operator-session                start_operator_session  {employee_guid, pin}
#           Checks: the person has a PIN, is not locked, is clocked in here (when
#           Toast can be asked), and the PIN is right.
#   DELETE  /api/operator-session                end_operator_session
#
# Admin:
#   GET     /api/operators                       list_pins          people with a PIN
#   GET     /api/operators/toast-employees       toast_employees    ?location_id  (live from Toast)
#   PUT     /api/operators/pin                   set_pin            {location_id, employee_guid, pin}
#   DELETE  /api/operators/<id>                  remove_pin         (signs them out)
#   POST    /api/operators/<id>/unlock           unlock_pin
#   GET     /api/operators/toast-status          toast_status
# =============================================================================

import logging
import re
import secrets

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash

from core.auth import admin_required, any_role_required, _is_admin, _get_user_location
from core.database import get_engine
from core import toast_api
from core.operators import (
    current_session, is_shared_login, hash_token,
    IDLE_MINUTES, MAX_PIN_TRIES, LOCK_MINUTES, PIN_LENGTH,
)

logger = logging.getLogger(__name__)

bp = Blueprint('operator_routes', __name__, url_prefix='/api')

PIN_RE = re.compile(r'^\d{%d}$' % PIN_LENGTH)


def _device_location(conn):
    """The location this device signs in at: the login's own, or (admins) location_id."""
    requested = request.args.get('location_id') or (request.get_json(silent=True) or {}).get('location_id')
    if requested and _is_admin():
        return str(requested)
    return _get_user_location(conn)


def _location_name(conn, location_id):
    return conn.execute(text("SELECT location_name FROM locations WHERE store_guid::text = :id"),
                        {'id': str(location_id)}).scalar() if location_id else None


def _toast_clocked_in(location_id):
    """(set of clocked-in employee GUIDs, {guid: employee}) or (None, None) when Toast cannot be asked."""
    if not toast_api.is_configured():
        return None, None
    try:
        clocked = toast_api.get_clocked_in(location_id)
        employees = {e['guid']: e for e in toast_api.get_employees(location_id) if e.get('guid')}
        return clocked, employees
    except toast_api.ToastError as e:
        logger.warning(f'Toast clocked-in check for {location_id}: {e}')
        return None, None


# =============================================================================
# Sign-in
# =============================================================================

@bp.route('/operator-session', methods=['GET'])
@any_role_required
def current_operator_session():
    """Who is signed in on this device, and whether this login needs someone to sign in."""
    with get_engine().begin() as conn:
        location_id = _device_location(conn)
        s = current_session(conn, location_id) if location_id else current_session(conn)
        shared = is_shared_login(conn, location_id) if location_id else False
        name = _location_name(conn, location_id)
    return jsonify({
        'location_id':   location_id,
        'location_name': name,
        'shared':        shared,
        'idle_minutes':  IDLE_MINUTES,
        'pin_length':    PIN_LENGTH,
        'operator':      ({'name': s['display_name'], 'employee_guid': s['toast_employee_guid']}
                          if s else None),
    })


@bp.route('/operator-sign-in/people', methods=['GET'])
@any_role_required
def sign_in_people():
    with get_engine().connect() as conn:
        location_id = _device_location(conn)
        if not location_id:
            return jsonify({'error': 'This login is not linked to a location'}), 400
        pins = {r['toast_employee_guid']: r for r in conn.execute(text("""
            SELECT toast_employee_guid, display_name, locked_until > NOW() AS locked
            FROM employee_pins
        """)).mappings().all()}

    clocked, employees = _toast_clocked_in(location_id)
    if clocked is None:
        # Toast could not be asked: everyone with a PIN may sign in.
        people = [{'employee_guid': guid, 'name': p['display_name'], 'has_pin': True,
                   'locked': bool(p['locked'])} for guid, p in pins.items()]
        source = 'pins'
    else:
        people = []
        for guid in clocked:
            p = pins.get(guid)
            e = employees.get(guid)
            name = toast_api.display_name(e) if e else (p['display_name'] if p else 'Unknown')
            people.append({'employee_guid': guid, 'name': name, 'has_pin': bool(p),
                           'locked': bool(p and p['locked'])})
        source = 'toast'
    people.sort(key=lambda x: (not x['has_pin'], x['name'].lower()))
    return jsonify({'location_id': location_id, 'source': source, 'people': people,
                    'pin_length': PIN_LENGTH,
                    'toast': 'ok' if source == 'toast' else
                             ('not_configured' if not toast_api.is_configured() else 'error')})


@bp.route('/operator-session', methods=['POST'])
@any_role_required
def start_operator_session():
    """Body: {employee_guid, pin}. Signs the person in on this device (ends whoever was signed in)."""
    data = request.get_json(force=True) or {}
    guid = str(data.get('employee_guid') or '').strip()
    pin = str(data.get('pin') or '')
    if not guid:
        return jsonify({'error': 'Pick your name'}), 400

    with get_engine().begin() as conn:
        location_id = _device_location(conn)
        if not location_id:
            return jsonify({'error': 'This login is not linked to a location'}), 400
        p = conn.execute(text("""
            SELECT id, display_name, pin_hash, failed_pin_count,
                   locked_until > NOW() AS locked,
                   CEIL(EXTRACT(EPOCH FROM (locked_until - NOW())) / 60) AS locked_minutes
            FROM employee_pins WHERE toast_employee_guid = :g
            FOR UPDATE
        """), {'g': guid}).mappings().fetchone()
        if not p:
            return jsonify({'error': 'You do not have a PIN yet. Ask an admin to set one.',
                            'code': 'no_pin'}), 403
        if p['locked']:
            return jsonify({'error': f"Too many wrong PINs. Try again in {int(p['locked_minutes'] or 1)} "
                                     f"minute(s), or ask an admin to unlock.", 'code': 'locked'}), 423

        # Must be clocked in here, when Toast can tell us.
        clocked, employees = _toast_clocked_in(location_id)
        if clocked is not None and guid not in clocked:
            return jsonify({'error': 'You are not clocked in here on Toast. Clock in first.',
                            'code': 'not_clocked_in'}), 403

        if not check_password_hash(p['pin_hash'], pin):
            tries = p['failed_pin_count'] + 1
            if tries >= MAX_PIN_TRIES:
                conn.execute(text("""
                    UPDATE employee_pins SET failed_pin_count = 0,
                           locked_until = NOW() + make_interval(mins => :m) WHERE id = :id
                """), {'id': p['id'], 'm': LOCK_MINUTES})
                return jsonify({'error': f'Too many wrong PINs. Locked for {LOCK_MINUTES} minutes.',
                                'code': 'locked'}), 423
            conn.execute(text("UPDATE employee_pins SET failed_pin_count = :n WHERE id = :id"),
                         {'id': p['id'], 'n': tries})
            return jsonify({'error': 'Wrong PIN', 'code': 'wrong_pin',
                            'tries_left': MAX_PIN_TRIES - tries}), 401

        # Keep the name as Toast has it now
        name = p['display_name']
        e = (employees or {}).get(guid)
        if e:
            name = toast_api.display_name(e)
            conn.execute(text("""
                UPDATE employee_pins SET first_name = :f, last_name = :l, display_name = :d,
                       name_checked_at = NOW() WHERE id = :id
            """), {'f': e.get('firstName'), 'l': e.get('lastName'), 'd': name, 'id': p['id']})

        old = request.headers.get('X-Operator-Session')
        if old:
            conn.execute(text("""
                UPDATE operator_sessions SET ended_at = NOW(), end_reason = 'switched'
                WHERE token_hash = :h AND ended_at IS NULL
            """), {'h': hash_token(old)})
        token = secrets.token_urlsafe(32)
        conn.execute(text("""
            INSERT INTO operator_sessions (token_hash, employee_pin_id, location_id, login_email)
            VALUES (:h, :pid, :lid, :email)
        """), {'h': hash_token(token), 'pid': p['id'], 'lid': location_id,
               'email': g.user.get('email')})
        conn.execute(text("""
            UPDATE employee_pins SET failed_pin_count = 0, locked_until = NULL, last_used_at = NOW()
            WHERE id = :id
        """), {'id': p['id']})
    return jsonify({'token': token, 'operator': {'name': name, 'employee_guid': guid},
                    'idle_minutes': IDLE_MINUTES})


@bp.route('/operator-session', methods=['DELETE'])
@any_role_required
def end_operator_session():
    token = request.headers.get('X-Operator-Session')
    if token:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE operator_sessions SET ended_at = NOW(), end_reason = 'signed_out'
                WHERE token_hash = :h AND ended_at IS NULL
            """), {'h': hash_token(token)})
    return jsonify({'status': 'ok'})


# =============================================================================
# Admin: PINs
# =============================================================================

@bp.route('/operators', methods=['GET'])
@admin_required
def list_pins():
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT id, toast_employee_guid, first_name, last_name, display_name, name_checked_at,
                   pin_set_at, pin_set_by, locked_until > NOW() AS locked, last_used_at
            FROM employee_pins ORDER BY display_name
        """)).mappings().all()
    return jsonify([dict(r) for r in rows])


@bp.route('/operators/toast-status', methods=['GET'])
@admin_required
def toast_status():
    return jsonify({'configured': toast_api.is_configured(), 'pin_length': PIN_LENGTH})


@bp.route('/operators/toast-employees', methods=['GET'])
@admin_required
def toast_employees():
    """A location's employees, read live from Toast (not stored), with who already has a PIN."""
    location_id = request.args.get('location_id')
    if not location_id:
        return jsonify({'error': 'Choose a location'}), 400
    if not toast_api.is_configured():
        return jsonify({'error': 'The Toast API is not set up on the server '
                                 '(TOAST_CLIENT_ID / TOAST_CLIENT_SECRET)'}), 400
    try:
        employees = toast_api.get_employees(location_id, use_cache=False)
    except toast_api.ToastError as e:
        return jsonify({'error': str(e)}), 502
    with get_engine().connect() as conn:
        pins = {r.toast_employee_guid: r.id for r in conn.execute(text(
            "SELECT id, toast_employee_guid FROM employee_pins")).fetchall()}
    out = [{'employee_guid': e['guid'], 'name': toast_api.display_name(e),
            'first_name': e.get('firstName'), 'last_name': e.get('lastName'),
            'pin_id': pins.get(e['guid'])}
           for e in employees if e.get('guid') and not e.get('deleted')]
    out.sort(key=lambda x: x['name'].lower())
    return jsonify(out)


@bp.route('/operators/pin', methods=['PUT'])
@admin_required
def set_pin():
    """Body: {location_id, employee_guid, pin}. The employee is checked against Toast (that location)."""
    data = request.get_json(force=True) or {}
    guid = str(data.get('employee_guid') or '').strip()
    pin = str(data.get('pin') or '')
    if not guid or not data.get('location_id'):
        return jsonify({'error': 'location_id and employee_guid are required'}), 400
    if not PIN_RE.match(pin):
        return jsonify({'error': f'The PIN must be exactly {PIN_LENGTH} digits'}), 400
    try:
        employees = toast_api.get_employees(data['location_id'])
    except toast_api.ToastError as e:
        return jsonify({'error': str(e)}), 502
    e = next((x for x in employees if x.get('guid') == guid and not x.get('deleted')), None)
    if not e:
        return jsonify({'error': 'That employee was not found at this location in Toast'}), 404
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO employee_pins (toast_employee_guid, toast_v2_employee_guid, first_name, last_name,
                                       display_name, name_checked_at, pin_hash, pin_set_at, pin_set_by)
            VALUES (:g, :g2, :f, :l, :d, NOW(), :h, NOW(), :by)
            ON CONFLICT (toast_employee_guid) DO UPDATE SET
                toast_v2_employee_guid = EXCLUDED.toast_v2_employee_guid,
                first_name = EXCLUDED.first_name, last_name = EXCLUDED.last_name,
                display_name = EXCLUDED.display_name, name_checked_at = NOW(),
                pin_hash = EXCLUDED.pin_hash, pin_set_at = NOW(), pin_set_by = EXCLUDED.pin_set_by,
                failed_pin_count = 0, locked_until = NULL
        """), {'g': guid, 'g2': e.get('v2EmployeeGuid'), 'f': e.get('firstName'), 'l': e.get('lastName'),
               'd': toast_api.display_name(e), 'h': generate_password_hash(pin),
               'by': g.user.get('email')})
    return jsonify({'status': 'ok', 'name': toast_api.display_name(e)})


@bp.route('/operators/<int:pin_id>', methods=['DELETE'])
@admin_required
def remove_pin(pin_id):
    """Remove someone's PIN. They are signed out; past sign-offs keep their name."""
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM employee_pins WHERE id = :id"), {'id': pin_id})
    return jsonify({'status': 'ok'})


@bp.route('/operators/<int:pin_id>/unlock', methods=['POST'])
@admin_required
def unlock_pin(pin_id):
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE employee_pins SET failed_pin_count = 0, locked_until = NULL WHERE id = :id
        """), {'id': pin_id})
    return jsonify({'status': 'ok'})
