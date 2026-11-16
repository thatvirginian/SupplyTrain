# =============================================================================
# backend/features/transfers/transfer_routes.py
# =============================================================================
# Transfers: product sent from one store to another. A record of what moved,
# who sent it and who received it. It does not change any inventory or order.
#
# Lifecycle
#   open      created by either store; lines can still be changed
#   sent      the sending store marked it sent; locked
#   received  the receiving store confirmed what arrived (received qty per line)
#   cancelled open: either store (or admin) may cancel; sent: admin only
#   An admin or the sending store may take a sent transfer back to open.
#
# Who: admin sees and does everything. Any other staff user (not readonly)
# sees transfers in or out of their own store (locations.contact_email).
#
# Endpoints in this file:
#   GET     /api/transfers                       list_transfers
#   GET     /api/transfers/products              search_transfer_products
#   POST    /api/transfers                       create_transfer
#   GET     /api/transfers/<int:transfer_id>     get_transfer
#   PUT     /api/transfers/<int:transfer_id>     update_transfer
#   DELETE  /api/transfers/<int:transfer_id>     delete_transfer
#   POST    /api/transfers/<int:transfer_id>/send     send_transfer
#   POST    /api/transfers/<int:transfer_id>/reopen   reopen_transfer
#   POST    /api/transfers/<int:transfer_id>/receive  receive_transfer
#   POST    /api/transfers/<int:transfer_id>/cancel   cancel_transfer
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
from datetime import date
import logging

from core.auth import (
    staff_required, admin_required, _is_admin, _get_user_location,
)
from core.database import get_engine
from core.units import (
    load_base_units, load_conversion_map, base_factor, load_unit_choices,
)

logger = logging.getLogger(__name__)

bp = Blueprint('transfer_routes', __name__, url_prefix='/api')

REASONS = ('shortage', 'catering', 'event', 'overstock', 'other')


class TransferError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status  = status


def _err(e):
    return jsonify({'error': e.message}), e.status


def _load_header(conn, transfer_id, lock=False):
    row = conn.execute(text(f"""
        SELECT * FROM transfers WHERE id = :id {'FOR UPDATE' if lock else ''}
    """), {'id': transfer_id}).mappings().fetchone()
    if not row:
        raise TransferError('Transfer not found', 404)
    return dict(row)


def _user_side(conn, t):
    """
    'admin', 'from', 'to' or None. Raises 404 when the user may not see it
    (no hint that the transfer exists).
    """
    if _is_admin():
        return 'admin'
    loc = _get_user_location(conn)
    if loc and loc == t['from_location_id']:
        return 'from'
    if loc and loc == t['to_location_id']:
        return 'to'
    raise TransferError('Transfer not found', 404)


def _actions(side, status):
    """What this user may do now. The detail page reads this; the routes enforce the same rules."""
    admin = side == 'admin'
    return {
        'can_edit':    status == 'open' and side in ('admin', 'from', 'to'),
        'can_send':    status == 'open' and side in ('admin', 'from'),
        'can_reopen':  status == 'sent' and side in ('admin', 'from'),
        'can_receive': status == 'sent' and side in ('admin', 'to'),
        'can_cancel':  (status == 'open' and side in ('admin', 'from', 'to'))
                       or (status == 'sent' and admin),
        'can_delete':  admin,
    }


def _clean_lines(conn, items):
    """
    Validate lines and compute base quantities. Returns rows ready to insert.
    Lines with no quantity (blank or 0) are dropped.
    """
    lines, seen = [], set()
    for raw in items or []:
        try:
            pid = int(raw.get('product_id'))
            qty = float(raw.get('quantity') or 0)
            uid = int(raw['unit_id']) if raw.get('unit_id') else None
        except (TypeError, ValueError):
            raise TransferError('Every line needs a product and a number quantity')
        if qty <= 0:
            continue
        if pid in seen:
            raise TransferError('A product is listed twice; combine the lines')
        seen.add(pid)
        lines.append({'product_id': pid, 'quantity': qty, 'unit_id': uid,
                      'notes': (raw.get('notes') or '').strip() or None})
    if not lines:
        raise TransferError('Add at least one item with a quantity')

    pids  = [l['product_id'] for l in lines]
    names = {r.id: r.name for r in conn.execute(text("""
        SELECT id, name FROM products WHERE id = ANY(:ids)
    """), {'ids': pids}).fetchall()}
    missing = [p for p in pids if p not in names]
    if missing:
        raise TransferError(f'Product(s) not found: {missing}', 404)

    choices    = load_unit_choices(conn, pids)
    base_units = load_base_units(conn, pids)
    for l in lines:
        if l['unit_id'] is None:
            l['unit_id'] = base_units.get(l['product_id'])
    conv_map = load_conversion_map(conn, pids, {l['unit_id'] for l in lines}, set(base_units.values()))

    for i, l in enumerate(lines):
        if not any(u['id'] == l['unit_id'] for u in choices.get(l['product_id'], [])):
            raise TransferError(f"{names[l['product_id']]}: that unit has no conversion to the product's base unit")
        f = base_factor(conv_map, l['unit_id'], base_units[l['product_id']], l['product_id'])
        l['product_name']  = names[l['product_id']]
        l['base_unit_id']  = base_units[l['product_id']]
        l['base_quantity'] = round(l['quantity'] * f, 4)
        l['sort_order']    = i
    return lines


def _write_lines(conn, transfer_id, lines):
    conn.execute(text("DELETE FROM transfer_items WHERE transfer_id = :id"), {'id': transfer_id})
    conn.execute(text("""
        INSERT INTO transfer_items (
            transfer_id, product_id, product_name, quantity, unit_id,
            base_quantity, base_unit_id, notes, sort_order
        ) VALUES (
            :transfer_id, :product_id, :product_name, :quantity, :unit_id,
            :base_quantity, :base_unit_id, :notes, :sort_order
        )
    """), [{**l, 'transfer_id': transfer_id} for l in lines])


def _check_locations(conn, from_loc, to_loc):
    if not from_loc or not to_loc:
        raise TransferError('Pick both the sending and the receiving store')
    if from_loc == to_loc:
        raise TransferError('A store cannot transfer to itself')
    found = {r.g for r in conn.execute(text("""
        SELECT store_guid::text AS g FROM locations WHERE store_guid::text = ANY(:ids)
    """), {'ids': [from_loc, to_loc]}).fetchall()}
    if from_loc not in found or to_loc not in found:
        raise TransferError('Location not found', 404)


# =============================================================================
# List / search
# =============================================================================

@bp.route('/transfers', methods=['GET'])
@staff_required
def list_transfers():
    """
    ?status=  ?direction=incoming|outgoing  ?location_id= (admin)  ?page= ?per_page=
    Non-admins only ever see transfers into or out of their own store.
    """
    status    = request.args.get('status')
    direction = request.args.get('direction')
    page      = max(1, request.args.get('page', 1, type=int))
    per_page  = min(100, max(1, request.args.get('per_page', 20, type=int)))

    filters = []
    params  = {'limit': per_page, 'offset': (page - 1) * per_page}

    with get_engine().connect() as conn:
        if _is_admin():
            loc = request.args.get('location_id') or None
        else:
            loc = _get_user_location(conn)
            if not loc:
                return jsonify({'total': 0, 'page': 1, 'per_page': per_page, 'pages': 1,
                                'transfers': [], 'my_location_id': None})

        if loc:
            params['loc'] = loc
            if direction == 'incoming':
                filters.append('t.to_location_id = :loc')
            elif direction == 'outgoing':
                filters.append('t.from_location_id = :loc')
            else:
                filters.append('(t.from_location_id = :loc OR t.to_location_id = :loc)')
        if status:
            filters.append('t.status = :status')
            params['status'] = status

        where = ('WHERE ' + ' AND '.join(filters)) if filters else ''

        total = conn.execute(text(f"SELECT COUNT(*) FROM transfers t {where}"), params).scalar()
        rows = conn.execute(text(f"""
            SELECT
                t.id, t.from_location_id, t.to_location_id, t.transfer_date,
                t.status, t.reason, t.notes, t.created_by, t.created_at,
                t.sent_at, t.received_at,
                lf.location_name AS from_location_name,
                lt.location_name AS to_location_name,
                (SELECT COUNT(*) FROM transfer_items ti WHERE ti.transfer_id = t.id) AS line_item_count
            FROM transfers t
            LEFT JOIN locations lf ON lf.store_guid::text = t.from_location_id
            LEFT JOIN locations lt ON lt.store_guid::text = t.to_location_id
            {where}
            ORDER BY t.transfer_date DESC, t.id DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return jsonify({
        'total':          total,
        'page':           page,
        'per_page':       per_page,
        'pages':          max(1, (total + per_page - 1) // per_page),
        'transfers':      [dict(r) for r in rows],
        'my_location_id': None if _is_admin() else loc,
    })


@bp.route('/transfers/products', methods=['GET'])
@staff_required
def search_transfer_products():
    """Active products matching ?search= (min 2 letters), with the units they can be sent in."""
    search = (request.args.get('search') or '').strip()
    if len(search) < 2:
        return jsonify([])
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT p.id AS product_id, p.name AS product_name, p.base_unit_id,
                   bu.name AS base_unit, c.name AS category_name,
                   vi.order_unit_id
            FROM products p
            LEFT JOIN units bu              ON bu.id = p.base_unit_id
            LEFT JOIN product_categories c  ON c.id  = p.category_id
            LEFT JOIN vendor_items vi       ON vi.product_id = p.id AND vi.active = TRUE
            WHERE p.active = TRUE
              AND (p.name ILIKE :like OR p.internal_name ILIKE :like OR p.sku ILIKE :like)
            ORDER BY (p.name ILIKE :prefix) DESC, p.name
            LIMIT 25
        """), {'like': f'%{search}%', 'prefix': f'{search}%'}).mappings().all()
        products = [dict(r) for r in rows]
        choices  = load_unit_choices(conn, [p['product_id'] for p in products])
    for p in products:
        p['units'] = choices.get(p['product_id'], [])
        # Default to the unit the store usually orders in (a case), if it converts
        ids = {u['id'] for u in p['units']}
        p['default_unit_id'] = p['order_unit_id'] if p['order_unit_id'] in ids else p['base_unit_id']
    return jsonify(products)


# =============================================================================
# Create / read / update / delete
# =============================================================================

@bp.route('/transfers', methods=['POST'])
@staff_required
def create_transfer():
    """
    Body: from_location_id, to_location_id, transfer_date (default today),
          reason, notes, items [{product_id, quantity, unit_id, notes}]
    A non-admin must be one of the two stores (usually the sender, but the
    receiving store may also write it up).
    """
    data     = request.get_json(force=True) or {}
    from_loc = data.get('from_location_id')
    to_loc   = data.get('to_location_id')
    reason   = data.get('reason') or None
    try:
        if reason and reason not in REASONS:
            raise TransferError(f'Unknown reason: {reason}')
        with get_engine().begin() as conn:
            if not _is_admin():
                mine = _get_user_location(conn)
                if not mine:
                    raise TransferError('Your account is not linked to a location', 403)
                if mine not in (from_loc, to_loc):
                    raise TransferError('Your store must be the sending or the receiving store', 403)
            _check_locations(conn, from_loc, to_loc)
            lines = _clean_lines(conn, data.get('items'))

            tid = conn.execute(text("""
                INSERT INTO transfers (
                    from_location_id, to_location_id, transfer_date,
                    status, reason, notes, created_by
                ) VALUES (
                    :from_loc, :to_loc, :transfer_date,
                    'open', :reason, :notes, :by
                ) RETURNING id
            """), {
                'from_loc':      from_loc,
                'to_loc':        to_loc,
                'transfer_date': data.get('transfer_date') or date.today().isoformat(),
                'reason':        reason,
                'notes':         (data.get('notes') or '').strip() or None,
                'by':            g.user.get('email'),
            }).fetchone().id
            _write_lines(conn, tid, lines)
        return jsonify({'id': tid}), 201
    except TransferError as e:
        return _err(e)
    except Exception as e:
        logger.error(f'create_transfer: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/transfers/<int:transfer_id>', methods=['GET'])
@staff_required
def get_transfer(transfer_id):
    try:
        with get_engine().connect() as conn:
            t    = _load_header(conn, transfer_id)
            side = _user_side(conn, t)
            names = {r.g: r.location_name for r in conn.execute(text("""
                SELECT store_guid::text AS g, location_name FROM locations
                WHERE store_guid::text = ANY(:ids)
            """), {'ids': [t['from_location_id'], t['to_location_id']]}).fetchall()}
            items = conn.execute(text("""
                SELECT ti.id, ti.product_id, ti.product_name, ti.quantity, ti.unit_id,
                       u.name AS unit, ti.base_quantity, ti.base_unit_id, bu.name AS base_unit,
                       ti.received_quantity, ti.received_base_quantity, ti.received_base_unit_id,
                       rbu.name AS received_base_unit,
                       ti.received_note, ti.notes, ti.sort_order
                FROM transfer_items ti
                LEFT JOIN units u  ON u.id  = ti.unit_id
                LEFT JOIN units bu ON bu.id = ti.base_unit_id
                LEFT JOIN units rbu ON rbu.id = ti.received_base_unit_id
                WHERE ti.transfer_id = :id
                ORDER BY ti.sort_order, ti.product_name
            """), {'id': transfer_id}).mappings().all()
            items = [dict(i) for i in items]
            # Unit choices, so an open transfer can be edited in place
            choices = load_unit_choices(conn, [i['product_id'] for i in items])
            for i in items:
                i['units'] = choices.get(i['product_id'], [])
    except TransferError as e:
        return _err(e)

    t['from_location_name'] = names.get(t['from_location_id'])
    t['to_location_name']   = names.get(t['to_location_id'])
    t['items']   = items
    t['my_side'] = side
    t.update(_actions(side, t['status']))
    return jsonify(t)


@bp.route('/transfers/<int:transfer_id>', methods=['PUT'])
@staff_required
def update_transfer(transfer_id):
    """
    While open: change transfer_date, reason, notes, the stores, and/or the
    lines (send 'items' to replace all lines).
    """
    data = request.get_json(force=True) or {}
    try:
        with get_engine().begin() as conn:
            t    = _load_header(conn, transfer_id, lock=True)
            side = _user_side(conn, t)
            if not _actions(side, t['status'])['can_edit']:
                raise TransferError(f"A {t['status']} transfer cannot be changed", 400)

            from_loc = data.get('from_location_id', t['from_location_id'])
            to_loc   = data.get('to_location_id',   t['to_location_id'])
            if (from_loc, to_loc) != (t['from_location_id'], t['to_location_id']):
                _check_locations(conn, from_loc, to_loc)
                if side != 'admin':
                    mine = _get_user_location(conn)
                    if mine not in (from_loc, to_loc):
                        raise TransferError('Your store must stay the sending or the receiving store', 403)

            reason = data.get('reason', t['reason']) or None
            if reason and reason not in REASONS:
                raise TransferError(f'Unknown reason: {reason}')

            conn.execute(text("""
                UPDATE transfers SET
                    from_location_id = :from_loc,
                    to_location_id   = :to_loc,
                    transfer_date    = :transfer_date,
                    reason           = :reason,
                    notes            = :notes,
                    updated_at       = NOW()
                WHERE id = :id
            """), {
                'id':            transfer_id,
                'from_loc':      from_loc,
                'to_loc':        to_loc,
                'transfer_date': data.get('transfer_date') or t['transfer_date'],
                'reason':        reason,
                'notes':         ((data['notes'] or '').strip() or None) if 'notes' in data else t['notes'],
            })
            if 'items' in data:
                _write_lines(conn, transfer_id, _clean_lines(conn, data['items']))
        return jsonify({'status': 'ok'})
    except TransferError as e:
        return _err(e)
    except Exception as e:
        logger.error(f'update_transfer: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/transfers/<int:transfer_id>', methods=['DELETE'])
@admin_required
def delete_transfer(transfer_id):
    """Delete a transfer and its lines. Admin only (others cancel instead)."""
    try:
        with get_engine().begin() as conn:
            n = conn.execute(text("DELETE FROM transfers WHERE id = :id"), {'id': transfer_id}).rowcount
        if not n:
            return jsonify({'error': 'Transfer not found'}), 404
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_transfer: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Lifecycle
# =============================================================================

def _transition(transfer_id, action, apply):
    """Load + lock, check the action is allowed for this user, run apply(conn, t)."""
    try:
        with get_engine().begin() as conn:
            t    = _load_header(conn, transfer_id, lock=True)
            side = _user_side(conn, t)
            if not _actions(side, t['status'])[action]:
                raise TransferError(f"Not allowed on a {t['status']} transfer", 400 if side == 'admin' else 403)
            apply(conn, t)
        return jsonify({'status': 'ok'})
    except TransferError as e:
        return _err(e)
    except Exception as e:
        logger.error(f'transfer {action}: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/transfers/<int:transfer_id>/send', methods=['POST'])
@staff_required
def send_transfer(transfer_id):
    """Sending store (or admin): open -> sent. Locks the lines."""
    def apply(conn, t):
        n = conn.execute(text("SELECT COUNT(*) FROM transfer_items WHERE transfer_id = :id"),
                         {'id': transfer_id}).scalar()
        if not n:
            raise TransferError('Add at least one item before sending')
        conn.execute(text("""
            UPDATE transfers SET status = 'sent', sent_at = NOW(), sent_by = :by, updated_at = NOW()
            WHERE id = :id
        """), {'id': transfer_id, 'by': g.user.get('email')})
    return _transition(transfer_id, 'can_send', apply)


@bp.route('/transfers/<int:transfer_id>/reopen', methods=['POST'])
@staff_required
def reopen_transfer(transfer_id):
    """Sending store (or admin): sent -> open, to fix a line before it is received."""
    def apply(conn, t):
        conn.execute(text("""
            UPDATE transfers SET status = 'open', sent_at = NULL, sent_by = NULL, updated_at = NOW()
            WHERE id = :id
        """), {'id': transfer_id})
    return _transition(transfer_id, 'can_reopen', apply)


@bp.route('/transfers/<int:transfer_id>/receive', methods=['POST'])
@staff_required
def receive_transfer(transfer_id):
    """
    Receiving store (or admin): sent -> received.
    Body: { items: [{id, received_quantity, received_note}], received_note }
    A line not listed is received in full (received_quantity = quantity).
    Each line also stores received_base_quantity + received_base_unit_id.
    """
    data = request.get_json(force=True) or {}

    def apply(conn, t):
        by_id = {}
        for raw in data.get('items') or []:
            try:
                iid = int(raw['id'])
                rq  = raw.get('received_quantity')
                rq  = None if rq in (None, '') else float(rq)
            except (KeyError, TypeError, ValueError):
                raise TransferError('Received quantities must be numbers')
            if rq is not None and rq < 0:
                raise TransferError('Received quantity cannot be negative')
            by_id[iid] = {'rq': rq, 'note': (raw.get('received_note') or '').strip() or None}

        lines = conn.execute(text("""
            SELECT id, product_id, product_name, quantity, unit_id
            FROM transfer_items WHERE transfer_id = :id
        """), {'id': transfer_id}).fetchall()
        unknown = set(by_id) - {r.id for r in lines}
        if unknown:
            raise TransferError(f'Line(s) {sorted(unknown)} are not on this transfer')

        # Received amount in base units, converted now (base unit from products,
        # today's conversion), same as every other saved amount.
        pids       = [r.product_id for r in lines]
        base_units = load_base_units(conn, pids)
        conv_map   = load_conversion_map(conn, pids, {r.unit_id for r in lines}, set(base_units.values()))

        for r in lines:
            v  = by_id.get(r.id, {})
            rq = v.get('rq')
            if rq is None:
                rq = float(r.quantity)
            base_unit = base_units.get(r.product_id)
            f = base_factor(conv_map, r.unit_id, base_unit, r.product_id)
            if f is None:
                raise TransferError(f"{r.product_name}: its unit no longer converts to the product's base unit. "
                                    "Fix the conversion on the product, then receive again.")
            conn.execute(text("""
                UPDATE transfer_items SET
                    received_quantity      = :rq,
                    received_base_quantity = :rbq,
                    received_base_unit_id  = :rbu,
                    received_note          = :note
                WHERE id = :id
            """), {'id': r.id, 'rq': rq, 'rbq': round(rq * f, 4), 'rbu': base_unit,
                   'note': v.get('note')})

        conn.execute(text("""
            UPDATE transfers SET status = 'received', received_at = NOW(), received_by = :by,
                   received_note = :note, updated_at = NOW()
            WHERE id = :id
        """), {'id': transfer_id, 'by': g.user.get('email'),
               'note': (data.get('received_note') or '').strip() or None})
    return _transition(transfer_id, 'can_receive', apply)


@bp.route('/transfers/<int:transfer_id>/cancel', methods=['POST'])
@staff_required
def cancel_transfer(transfer_id):
    """Open: either store or admin. Sent: admin only. Received transfers cannot be cancelled."""
    def apply(conn, t):
        conn.execute(text("""
            UPDATE transfers SET status = 'cancelled', cancelled_at = NOW(), cancelled_by = :by,
                   updated_at = NOW()
            WHERE id = :id
        """), {'id': transfer_id, 'by': g.user.get('email')})
    return _transition(transfer_id, 'can_cancel', apply)
