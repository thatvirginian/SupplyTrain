# =============================================================================
# backend/features/inventory/inventory_count_routes.py
# =============================================================================
# Inventories (staff): inventory records. List, view, manual entry, save, submit, delete, and corrections with an audit trail.
#
# Endpoints in this file:
#   GET     /api/inventory-submissions                                          list_inventory_submissions
#   GET     /api/inventory-submissions/<int:submission_id>                      get_inventory_submission
#   PUT     /api/inventory-submissions/<int:submission_id>/items/<int:item_id>  correct_inventory_item
#   POST    /api/inventory-submissions                                          create_inventory_submission
#   PUT     /api/inventory-submissions/<int:submission_id>/save                 save_inventory_entries
#   POST    /api/inventory-submissions/<int:submission_id>/submit               submit_inventory
#   DELETE  /api/inventory-submissions/<int:submission_id>                      delete_inventory_submission
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
import logging

from core.auth import (
    gm_or_admin_required, staff_required, _is_admin, _get_user_location,
)
from core.database import get_engine
from core.units import load_base_units, load_conversion_map, base_factor

logger = logging.getLogger(__name__)

bp = Blueprint('inventory_count_routes', __name__, url_prefix='/api')


class AccessError(Exception):
    """Raised when the user may not touch this inventory. Carries the HTTP response."""
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def _load_submission_for_user(conn, submission_id):
    """
    Load an inventory header and check the user may access it.
    Admins: any location. Everyone else: only their own location.
    Raises AccessError(404) if missing, AccessError(403) if another location's.
    """
    sub = conn.execute(text("""
        SELECT id, status, location_id, count_date, source, template_id
        FROM inventory_submissions WHERE id = :id
    """), {'id': submission_id}).fetchone()
    if not sub:
        raise AccessError('Inventory not found', 404)
    if not _is_admin():
        user_location = _get_user_location(conn)
        if not user_location or str(user_location) != str(sub.location_id):
            raise AccessError('You do not have access to this inventory', 403)
    return sub


@bp.errorhandler(AccessError)
def _handle_access_error(e):
    return jsonify({'error': str(e)}), e.status


def _to_base(conn, product_id, unit_id, quantity):
    """Convert one quantity to the product's base unit. Returns (base_qty, base_unit_id) or (None, base_unit_id)."""
    base_unit_id = load_base_units(conn, [product_id]).get(product_id)
    conv = load_conversion_map(conn, [product_id], [unit_id], [base_unit_id]) if base_unit_id else {}
    factor = base_factor(conv, unit_id, base_unit_id, product_id)
    return (float(quantity) * factor if factor is not None else None), base_unit_id


# =============================================================================
# Inventory Submissions
# =============================================================================

@bp.route('/inventory-submissions', methods=['GET'])
@staff_required
def list_inventory_submissions():
    roles       = g.user.get('roles', [])
    is_admin    = 'admin' in roles
    location_id = request.args.get('location_id')
    source      = request.args.get('source')   # 'count_sheet' | 'manual'
    page        = request.args.get('page', 1, type=int)
    per_page    = request.args.get('per_page', 20, type=int)
    offset      = (page - 1) * per_page

    # Non-admins only ever see their own location, whatever they pass in.
    if not is_admin:
        with get_engine().connect() as conn:
            location_id = _get_user_location(conn)
        if not location_id:
            return jsonify({'error': 'No location is linked to your account'}), 403

    filters = []
    params  = {'limit': per_page, 'offset': offset}

    if location_id:
        filters.append('ivs.location_id = :location_id')
        params['location_id'] = location_id
    if source:
        filters.append('ivs.source = :source')
        params['source'] = source

    where = ('WHERE ' + ' AND '.join(filters)) if filters else ''

    with get_engine().connect() as conn:
        total = conn.execute(text(f"""
            SELECT COUNT(*) FROM inventory_submissions ivs {where}
        """), params).scalar()

        rows = conn.execute(text(f"""
            SELECT
                ivs.id, ivs.location_id, ivs.count_date,
                ivs.source, ivs.status,
                ivs.submitted_by, ivs.submitted_at,
                ivs.sheet_submission_id,
                ivs.template_id,
                ivs.notes, ivs.created_at,
                l.location_name,
                it.name AS template_name,
                COUNT(ic.id) AS item_count
            FROM inventory_submissions ivs
            LEFT JOIN locations l            ON l.store_guid::text = ivs.location_id
            LEFT JOIN inventory_templates it ON ivs.template_id    = it.id
            LEFT JOIN inventory_counts ic    ON ic.inventory_submission_id = ivs.id
            {where}
            GROUP BY ivs.id, l.location_name, it.name
            ORDER BY ivs.count_date DESC, ivs.created_at DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return jsonify({
        'total':       total,
        'page':        page,
        'per_page':    per_page,
        'pages':       max(1, (total + per_page - 1) // per_page),
        'submissions': [dict(r) for r in rows],
    })


@bp.route('/inventory-submissions/<int:submission_id>', methods=['GET'])
@staff_required
def get_inventory_submission(submission_id):
    with get_engine().connect() as conn:
        _load_submission_for_user(conn, submission_id)   # 404 / 403
        sub = conn.execute(text("""
            SELECT
                ivs.id, ivs.location_id, ivs.count_date,
                ivs.source, ivs.status, ivs.notes,
                ivs.submitted_by, ivs.submitted_at,
                ivs.sheet_submission_id, ivs.template_id,
                ivs.created_at, ivs.updated_at,
                l.location_name,
                it.name AS template_name
            FROM inventory_submissions ivs
            LEFT JOIN locations l            ON l.store_guid::text = ivs.location_id
            LEFT JOIN inventory_templates it ON ivs.template_id    = it.id
            WHERE ivs.id = :id
        """), {'id': submission_id}).mappings().fetchone()

        if not sub:
            return jsonify({'error': 'Inventory not found'}), 404

        items = conn.execute(text("""
            SELECT
                ic.id, ic.product_id, ic.count_date,
                ic.base_quantity, ic.base_unit_id,
                ic.entered_quantity, ic.entered_unit_id,
                ic.vendor_code, ic.vendor_id,
                ic.par_qty, ic.par_unit_id, ic.par_base_qty,
                ic.order_qty, ic.order_unit_id,
                ic.original_quantity, ic.corrected_by, ic.corrected_at,
                ic.correction_notes, ic.entered_by,
                p.name      AS product_name,
                c.name      AS category,
                u.name      AS base_unit,
                v.name      AS vendor_name,
                ou.name     AS order_unit,
                pu.name     AS par_unit
            FROM inventory_counts ic
            JOIN products p          ON ic.product_id   = p.id
            LEFT JOIN product_categories c ON p.category_id  = c.id
            LEFT JOIN units u        ON ic.base_unit_id  = u.id
            LEFT JOIN units ou       ON ic.order_unit_id = ou.id
            LEFT JOIN units pu       ON ic.par_unit_id   = pu.id
            LEFT JOIN vendors v      ON ic.vendor_id     = v.id
            WHERE ic.inventory_submission_id = :id
            ORDER BY c.name, p.name
        """), {'id': submission_id}).mappings().all()

        # For manual inventories fetch template sections
        template_sections = []
        if sub['template_id']:
            sections = conn.execute(text("""
                SELECT its.id, its.name, its.sort_order,
                    json_agg(
                        json_build_object(
                            'id',           iti.id,
                            'product_id',   iti.product_id,
                            'product_name', p.name,
                            'base_unit',    u.name,
                            'base_unit_id', p.base_unit_id
                        ) ORDER BY iti.sort_order
                    ) FILTER (WHERE iti.id IS NOT NULL) AS items
                FROM inventory_template_sections its
                LEFT JOIN inventory_template_items iti ON iti.section_id = its.id
                LEFT JOIN products p ON iti.product_id = p.id
                LEFT JOIN units u    ON p.base_unit_id = u.id
                WHERE its.template_id = :template_id
                GROUP BY its.id
                ORDER BY its.sort_order
            """), {'template_id': sub['template_id']}).mappings().all()

            # Fetch count units per item
            item_ids = []
            for s in sections:
                if s['items']:
                    item_ids.extend([i['id'] for i in s['items']])

            count_units_map = {}
            if item_ids:
                cu_rows = conn.execute(text("""
                    SELECT itiu.id, itiu.item_id, itiu.unit_id, itiu.sort_order,
                           u.name AS unit_name
                    FROM inventory_template_item_units itiu
                    JOIN units u ON itiu.unit_id = u.id
                    WHERE itiu.item_id = ANY(:item_ids)
                    ORDER BY itiu.item_id, itiu.sort_order
                """), {'item_ids': item_ids}).mappings().all()
                for cu in cu_rows:
                    iid = cu['item_id']
                    if iid not in count_units_map:
                        count_units_map[iid] = []
                    count_units_map[iid].append(dict(cu))

            for s in sections:
                sd = dict(s)
                if sd.get('items'):
                    for item in sd['items']:
                        item['count_units'] = count_units_map.get(item['id'], [])
                template_sections.append(sd)

        # The lines this inventory saved, exactly as typed (current rows only)
        entry_rows = conn.execute(text("""
            SELECT e.product_id, e.unit_id, e.quantity, e.base_quantity,
                   e.base_unit_id, e.entered_by, e.entered_at,
                   COALESCE(u.display, u.name) AS unit_name
            FROM inventory_count_entries e
            JOIN units u ON u.id = e.unit_id
            WHERE e.inventory_submission_id = :id AND e.superseded_at IS NULL
            ORDER BY e.product_id, e.unit_id
        """), {'id': submission_id}).mappings().all()

    result = dict(sub)
    result['items']             = [dict(i) for i in items]
    result['template_sections'] = template_sections
    result['entries']           = [dict(e) for e in entry_rows]
    return jsonify(result)


@bp.route('/inventory-submissions/<int:submission_id>/items/<int:item_id>', methods=['PUT'])
@gm_or_admin_required
def correct_inventory_item(submission_id, item_id):
    """
    Admin/GM correct a count, keeping the first value in original_quantity.
    Body: {quantity, unit_id, correction_notes}  (correct in any unit with a conversion)
       or {base_quantity, correction_notes}      (correct directly in base units)
    """
    data     = request.get_json(force=True) or {}
    quantity = data.get('quantity')
    unit_id  = data.get('unit_id')
    if quantity is None:
        quantity = data.get('base_quantity')
        unit_id  = None
    if quantity is None:
        return jsonify({'error': 'quantity is required'}), 400
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        return jsonify({'error': 'quantity must be a number'}), 400
    if quantity < 0:
        return jsonify({'error': 'quantity cannot be negative'}), 400

    try:
        with get_engine().begin() as conn:
            _load_submission_for_user(conn, submission_id)

            row = conn.execute(text("""
                SELECT product_id, base_unit_id FROM inventory_counts
                WHERE id = :id AND inventory_submission_id = :submission_id
            """), {'id': item_id, 'submission_id': submission_id}).fetchone()
            if not row:
                return jsonify({'error': 'Count not found on this inventory'}), 404

            if unit_id is None:
                unit_id      = row.base_unit_id
                base_qty     = quantity
                base_unit_id = row.base_unit_id
            else:
                base_qty, base_unit_id = _to_base(conn, row.product_id, int(unit_id), quantity)
                if base_qty is None:
                    return jsonify({'error': 'This unit has no conversion to the product\'s base unit'}), 400

            conn.execute(text("""
                UPDATE inventory_counts SET
                    original_quantity = COALESCE(original_quantity, base_quantity),
                    base_quantity     = :base_qty,
                    base_unit_id      = :base_unit_id,
                    entered_quantity  = :quantity,
                    entered_unit_id   = :unit_id,
                    corrected_by      = :corrected_by,
                    corrected_at      = NOW(),
                    correction_notes  = :correction_notes
                WHERE id = :id AND inventory_submission_id = :submission_id
            """), {
                'id':               item_id,
                'submission_id':    submission_id,
                'base_qty':         base_qty,
                'base_unit_id':     base_unit_id,
                'quantity':         quantity,
                'unit_id':          unit_id,
                'corrected_by':     g.user.get('email'),
                'correction_notes': data.get('correction_notes'),
            })
        return jsonify({'status': 'ok', 'base_quantity': base_qty})
    except AccessError:
        raise
    except Exception as e:
        logger.error(f'correct_inventory_item: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Manual inventory submissions (standalone)
# =============================================================================

@bp.route('/inventory-submissions', methods=['POST'])
@staff_required
def create_inventory_submission():
    """
    Create a new manual inventory.
    Staff: always their own location. Admins: must pass location_id.
    The template must be active and assigned to that location.
    """
    data        = request.get_json(force=True) or {}
    template_id = data.get('template_id')
    count_date  = data.get('count_date')

    if not count_date:
        return jsonify({'error': 'count_date is required'}), 400
    if not template_id:
        return jsonify({'error': 'template_id is required'}), 400

    try:
        with get_engine().begin() as conn:
            if _is_admin():
                location_id = data.get('location_id')
                if not location_id:
                    return jsonify({'error': 'Choose a location for this inventory'}), 400
            else:
                location_id = _get_user_location(conn)
                if not location_id:
                    return jsonify({'error': 'No location is linked to your account'}), 403
            location_id = str(location_id)

            assigned = conn.execute(text("""
                SELECT 1
                FROM inventory_templates it
                JOIN inventory_template_locations itl ON itl.template_id = it.id
                WHERE it.id = :template_id AND it.active = TRUE
                  AND itl.location_id = :location_id
            """), {'template_id': template_id, 'location_id': location_id}).fetchone()
            if not assigned:
                return jsonify({'error': 'That template is not assigned to this location'}), 400

            # Decision #10 (reuse an existing draft or not) is still open, so this
            # keeps today's behavior: every Start creates a new draft.
            result = conn.execute(text("""
                INSERT INTO inventory_submissions (
                    template_id, location_id, count_date,
                    source, status, submitted_by
                ) VALUES (
                    :template_id, :location_id, :count_date,
                    'manual', 'draft', :submitted_by
                )
                RETURNING id
            """), {
                'template_id':  template_id,
                'location_id':  location_id,
                'count_date':   count_date,
                'submitted_by': g.user.get('email'),
            })
            new_id = result.fetchone().id
        return jsonify({'id': new_id}), 201
    except Exception as e:
        logger.error(f'create_inventory_submission: {e}')
        return jsonify({'error': str(e)}), 500


def _parse_entry_lines(raw_entries):
    """
    Turn the page's entries into {(product_id, unit_id): quantity}.
    A product can sit in two template sections, so the page may send the same
    product+unit twice; the last value wins (it is the same box on screen).
    Raises ValueError with a message the user can read.
    """
    lines = {}
    for e in raw_entries or []:
        pid, uid, qty = e.get('product_id'), e.get('unit_id'), e.get('quantity')
        if not pid or not uid or qty is None or qty == '':
            continue
        try:
            q = float(qty)
        except (TypeError, ValueError):
            raise ValueError(f'"{qty}" is not a number')
        if q < 0:
            raise ValueError('Counts cannot be negative')
        lines[(int(pid), int(uid))] = q
    return lines


@bp.route('/inventory-submissions/<int:submission_id>/save', methods=['PUT'])
@staff_required
def save_inventory_entries(submission_id):
    """
    Save counts. Every unit line is converted to the product's base unit (read
    from products, not from the page) and the lines are added into ONE base
    figure per product in inventory_counts. The lines themselves are kept in
    inventory_count_entries so the sheet reloads exactly as typed.
    A line whose unit has no conversion is refused; nothing is saved.
    """
    data = request.get_json(force=True) or {}
    try:
        lines = _parse_entry_lines(data.get('entries'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    user = g.user.get('email')
    try:
        with get_engine().begin() as conn:
            sub = _load_submission_for_user(conn, submission_id)
            if not lines:
                return jsonify({'status': 'ok', 'saved': 0})

            product_ids = {pid for pid, _ in lines}
            unit_ids    = {uid for _, uid in lines}
            base_units  = load_base_units(conn, product_ids)
            conv_map    = load_conversion_map(conn, product_ids, unit_ids,
                                              {b for b in base_units.values() if b})

            # ── Convert every line; collect the ones we cannot convert ──────────
            per_product = {}   # pid -> {uid: (qty, base_qty)}
            missing     = []
            for (pid, uid), q in lines.items():
                base_uid = base_units.get(pid)
                factor   = base_factor(conv_map, uid, base_uid, pid)
                if factor is None:
                    missing.append((pid, uid))
                    continue
                per_product.setdefault(pid, {})[uid] = (q, q * factor)

            if missing:
                names = conn.execute(text("""
                    SELECT p.id AS product_id, p.name AS product_name,
                           u.id AS unit_id, COALESCE(u.display, u.name) AS unit_name,
                           COALESCE(bu.display, bu.name) AS base_unit
                    FROM unnest(CAST(:pids AS bigint[]), CAST(:uids AS integer[])) AS m(pid, uid)
                    LEFT JOIN products p ON p.id = m.pid
                    LEFT JOIN units u    ON u.id = m.uid
                    LEFT JOIN units bu   ON bu.id = p.base_unit_id
                """), {
                    'pids': [m[0] for m in missing],
                    'uids': [m[1] for m in missing],
                }).mappings().all()
                return jsonify({
                    'error': 'Some counts use a unit with no conversion to the product\'s '
                             'base unit. Nothing was saved. Ask an admin to add the conversion.',
                    'missing_conversions': [dict(n) for n in names],
                }), 400

            # ── Lines: supersede changed ones, insert new ones ─────────────────
            current = conn.execute(text("""
                SELECT id, product_id, unit_id, quantity
                FROM inventory_count_entries
                WHERE inventory_submission_id = :sid AND superseded_at IS NULL
                  AND product_id = ANY(:pids)
            """), {'sid': submission_id, 'pids': list(per_product)}).fetchall()
            current_by_product = {}
            for r in current:
                current_by_product.setdefault(r.product_id, {})[r.unit_id] = float(r.quantity)

            changed = []
            for pid, units in per_product.items():
                new_set = {uid: q for uid, (q, _) in units.items()}
                if current_by_product.get(pid) != new_set:
                    changed.append(pid)

            if changed:
                conn.execute(text("""
                    UPDATE inventory_count_entries
                    SET superseded_at = NOW(), superseded_by = :user
                    WHERE inventory_submission_id = :sid AND superseded_at IS NULL
                      AND product_id = ANY(:pids)
                """), {'sid': submission_id, 'pids': changed, 'user': user})
                conn.execute(text("""
                    INSERT INTO inventory_count_entries (
                        inventory_submission_id, product_id, unit_id,
                        quantity, base_quantity, base_unit_id, entered_by
                    ) VALUES (
                        :sid, :pid, :uid, :qty, :base_qty, :base_uid, :user
                    )
                """), [
                    {'sid': submission_id, 'pid': pid, 'uid': uid, 'qty': q,
                     'base_qty': bq, 'base_uid': base_units[pid], 'user': user}
                    for pid in changed
                    for uid, (q, bq) in per_product[pid].items()
                ])

            # ── The day's figure: one base total per product ───────────────────
            # entered_* holds the line when there is exactly one; with several
            # units it holds the base total (the lines live in the entries table).
            rows = []
            for pid, units in per_product.items():
                total = sum(bq for _, bq in units.values())
                if len(units) == 1:
                    (uid, (q, _)), = units.items()
                else:
                    uid, q = base_units[pid], total
                rows.append({
                    'inv_sub_id':       submission_id,
                    'location_id':      sub.location_id,
                    'product_id':       pid,
                    'count_date':       sub.count_date,
                    'base_quantity':    total,
                    'base_unit_id':     base_units[pid],
                    'entered_quantity': q,
                    'entered_unit_id':  uid,
                    'entered_by':       user,
                })
            conn.execute(text("""
                INSERT INTO inventory_counts (
                    inventory_submission_id, location_id, product_id,
                    count_date, base_quantity, base_unit_id,
                    entered_quantity, entered_unit_id, entered_by
                ) VALUES (
                    :inv_sub_id, :location_id, :product_id,
                    :count_date, :base_quantity, :base_unit_id,
                    :entered_quantity, :entered_unit_id, :entered_by
                )
                ON CONFLICT (location_id, product_id, count_date) DO UPDATE SET
                    base_quantity    = EXCLUDED.base_quantity,
                    base_unit_id     = EXCLUDED.base_unit_id,
                    entered_quantity = EXCLUDED.entered_quantity,
                    entered_unit_id  = EXCLUDED.entered_unit_id,
                    entered_by       = EXCLUDED.entered_by
            """), rows)

        return jsonify({'status': 'ok', 'saved': len(per_product)})
    except AccessError:
        raise
    except Exception as e:
        logger.error(f'save_inventory_entries: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-submissions/<int:submission_id>/submit', methods=['POST'])
@staff_required
def submit_inventory(submission_id):
    """Submit a manual inventory."""
    try:
        with get_engine().begin() as conn:
            sub = _load_submission_for_user(conn, submission_id)
            if sub.status == 'submitted':
                return jsonify({'error': 'Already submitted'}), 400

            conn.execute(text("""
                UPDATE inventory_submissions SET
                    status       = 'submitted',
                    submitted_by = :submitted_by,
                    submitted_at = NOW(),
                    updated_at   = NOW()
                WHERE id = :id
            """), {'id': submission_id, 'submitted_by': g.user.get('email')})

        return jsonify({'status': 'submitted'})
    except AccessError:
        raise
    except Exception as e:
        logger.error(f'submit_inventory: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-submissions/<int:submission_id>', methods=['DELETE'])
@gm_or_admin_required
def delete_inventory_submission(submission_id):
    """
    Delete an inventory header. Its saved lines (inventory_count_entries) go with it.
    The day's counts in inventory_counts are only detached, as before; what happens
    to them is decided in phase 2 (fall back to the previous inventory that day).
    """
    try:
        with get_engine().begin() as conn:
            _load_submission_for_user(conn, submission_id)
            conn.execute(text("""
                UPDATE inventory_counts SET inventory_submission_id = NULL
                WHERE inventory_submission_id = :id
            """), {'id': submission_id})
            conn.execute(text("""
                DELETE FROM inventory_submissions WHERE id = :id
            """), {'id': submission_id})
        return jsonify({'status': 'ok'})
    except AccessError:
        raise
    except Exception as e:
        logger.error(f'delete_inventory_submission: {e}')
        return jsonify({'error': str(e)}), 500
