# =============================================================================
# backend/core/operators.py
# =============================================================================
# WHO did it on a shared login: employee PINs, sign-in sessions and the
# sign-off log. The login (EasyAuth) still decides what the device may do; the
# signed-in employee only puts a person's name on the work.
#
# Only Toast employees an admin gave a PIN can sign in (table employee_pins;
# no copy of the Toast employee list is kept). They must be clocked in on
# Toast at the location; when Toast cannot be asked, anyone with a PIN may sign
# in (see features/operators/operator_routes.py).
#
# Shared login: the login email is the contact email of the location (that is
# how a login is matched to a location). On a shared login a signed action needs
# someone signed in. A personal login (anyone else) signs as itself.
#
# The device holds a random token (header X-Operator-Session); the server keeps
# only its sha256 in operator_sessions and ends a session after IDLE_MINUTES
# without use. A session only counts for the login that started it.
#
#   signer_for(conn, location_id)   -> {'employee_guid', 'name', 'login_email'}
#                                      raises OperatorRequired on a shared login
#                                      with nobody signed in
#   current_session(conn, location_id=None, touch=True) -> session dict or None
#   is_shared_login(conn, location_id) -> bool
#   record_signoff(conn, signer, action, entity_type, entity_id, location_id,
#                  line_id=None, note=None)
#   operator_required_response()    -> Flask (response, 428)
#   hash_token(token)               -> sha256 hex
#
# Use these inside get_engine().begin() so the session's last-seen time (and an
# idle session being ended) is saved.
# =============================================================================

import hashlib

from flask import g, jsonify, request
from sqlalchemy import text

IDLE_MINUTES   = 15
MAX_PIN_TRIES  = 5
LOCK_MINUTES   = 5
PIN_LENGTH     = 6
SESSION_HEADER = 'X-Operator-Session'


class OperatorRequired(Exception):
    """A signed action on a shared login with nobody signed in."""


def operator_required_response():
    return jsonify({'error': 'Sign in with your name and PIN first',
                    'code': 'operator_required'}), 428


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _login_email():
    return (g.user.get('email') or '').strip().lower()


def is_shared_login(conn, location_id):
    """True when the login email is that location's contact email (the shared device login)."""
    email = _login_email()
    if not email or not location_id:
        return False
    row = conn.execute(text("""
        SELECT 1 FROM locations
        WHERE store_guid::text = :lid AND LOWER(TRIM(contact_email)) = :email
    """), {'lid': str(location_id), 'email': email}).fetchone()
    return row is not None


def current_session(conn, location_id=None, touch=True):
    """
    The employee signed in on this device (the request's token), or None.
    Ends it when idle too long. With location_id, a session at another
    location does not count. A session only counts for the login that started
    it (an admin opening the shared tablet with their own login signs as
    themselves).
    """
    token = request.headers.get(SESSION_HEADER)
    if not token:
        return None
    s = conn.execute(text("""
        SELECT s.id, s.employee_pin_id, s.location_id, s.started_at, s.last_seen_at,
               s.last_seen_at < NOW() - make_interval(mins => :idle) AS idle,
               p.display_name, p.toast_employee_guid
        FROM operator_sessions s
        JOIN employee_pins p ON p.id = s.employee_pin_id
        WHERE s.token_hash = :h AND s.ended_at IS NULL
          AND LOWER(COALESCE(s.login_email, '')) = :email
    """), {'h': hash_token(token), 'idle': IDLE_MINUTES, 'email': _login_email()}).mappings().fetchone()
    if not s:
        return None
    if s['idle']:
        conn.execute(text("""
            UPDATE operator_sessions SET ended_at = NOW(), end_reason = 'idle' WHERE id = :id
        """), {'id': s['id']})
        return None
    if location_id and str(s['location_id']) != str(location_id):
        return None
    if touch:
        conn.execute(text("UPDATE operator_sessions SET last_seen_at = NOW() WHERE id = :id"),
                     {'id': s['id']})
    return dict(s)


def signer_for(conn, location_id):
    """Who signs an action at location_id. Raises OperatorRequired when nobody can."""
    s = current_session(conn, location_id)
    if s:
        conn.execute(text("UPDATE employee_pins SET last_used_at = NOW() WHERE id = :id"),
                     {'id': s['employee_pin_id']})
        return {'employee_guid': s['toast_employee_guid'], 'name': s['display_name'],
                'login_email': g.user.get('email')}
    if is_shared_login(conn, location_id):
        raise OperatorRequired()
    email = g.user.get('email') or 'unknown'
    return {'employee_guid': None, 'name': email, 'login_email': email}


def record_signoff(conn, signer, action, entity_type, entity_id, location_id,
                   line_id=None, note=None):
    conn.execute(text("""
        INSERT INTO operator_signoffs (toast_employee_guid, signer_name, login_email, location_id,
                                       action, entity_type, entity_id, line_id, note)
        VALUES (:guid, :name, :email, :lid, :action, :etype, :eid, :line, :note)
    """), {'guid': signer['employee_guid'], 'name': signer['name'], 'email': signer['login_email'],
           'lid': str(location_id) if location_id else None, 'action': action,
           'etype': entity_type, 'eid': entity_id, 'line': line_id, 'note': note})
