# =============================================================================
# backend/features/inventory/inventory_count_routes.py
# =============================================================================
# Inventories (staff): list, view, manual entry, save, submit, delete, corrections.
# The storage rules (drafts, latest submitted wins, fallback on delete) live in
# inventory_count_service.py; read its header first.
#
# Endpoints in this file:
#   GET     /api/inventory-submissions                                                list_inventory_submissions
#   GET     /api/inventory-submissions/<int:submission_id>                            get_inventory_submission
#   PUT     /api/inventory-submissions/<int:submission_id>/products/<int:product_id>  correct_inventory_product
#   POST    /api/inventory-submissions                                                create_inventory_submission
#   PUT     /api/inventory-submissions/<int:submission_id>/save                       save_inventory_entries
#   POST    /api/inventory-submissions/<int:submission_id>/submit                     submit_inventory
#   DELETE  /api/inventory-submissions/<int:submission_id>                            delete_inventory_submission
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
import logging

from core.auth import (
    gm_or_admin_required, staff_required, _is_admin, _get_user_location,
)
from core.database import get_engine
from core.units import load_base_units, load_conversion_map, base_factor
from features.inventory.inventory_count_service import (
    supersede_line_pairs, insert_lines, replace_product_lines,
    sync_counts_from_entries, refresh_day_counts, adopt_day_counts,
)

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
                -- Products counted: a draft only has lines; a submitted inventory has totals
                CASE WHEN ivs.status = 'draft' THEN (
                    SELECT COUNT(DISTINCT e.product_id) FROM inventory_count_entries e
                    WHERE e.inventory_submission_id = ivs.id AND e.superseded_at IS NULL
                ) ELSE (
                    SELECT COUNT(*) FROM inventory_submission_counts c
                    WHERE c.inventory_submission_id = ivs.id
                ) END AS item_count
            FROM inventory_submissions ivs
            LEFT JOIN locations l            ON l.store_guid::text = ivs.location_id
            LEFT JOIN inventory_templates it ON ivs.template_id    = it.id
            {where}
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

        # What THIS inventory counted, one row per product (base units).
        # is_day_count: this inventory currently holds the day's count for the product.
        items = conn.execute(text("""
            SELECT
                c.id, c.product_id,
                c.base_quantity, c.base_unit_id,
                c.entered_quantity, c.entered_unit_id,
                c.vendor_code, c.vendor_id,
                c.par_qty, c.par_unit_id, c.par_base_qty,
                c.order_qty, c.order_unit_id,
                c.original_quantity, c.corrected_by, c.corrected_at,
                c.correction_notes, c.entered_by,
                p.name      AS product_name,
                cat.name    AS category,
                u.name      AS base_unit,
                v.name      AS vendor_name,
                ou.name     AS order_unit,
                pu.name     AS par_unit,
                (d.id IS NOT NULL) AS is_day_count
            FROM inventory_submission_counts c
            JOIN products p                  ON c.product_id    = p.id
            LEFT JOIN product_categories cat ON p.category_id   = cat.id
            LEFT JOIN units u                ON c.base_unit_id  = u.id
            LEFT JOIN units ou               ON c.order_unit_id = ou.id
            LEFT JOIN units pu               ON c.par_unit_id   = pu.id
            LEFT JOIN vendors v              ON c.vendor_id     = v.id
            LEFT JOIN inventory_counts d
                   ON d.inventory_submission_id = c.inventory_submission_id
                  AND d.product_id              = c.product_id
            WHERE c.inventory_submission_id = :id
            ORDER BY cat.name, p.name
        """), {'id': submission_id}).mappings().all()

        if not items and sub['status'] == 'draft':
            # A draft has no totals yet: show what its saved lines add up to.
            items = conn.execute(text("""
                SELECT
                    NULL AS id, t.product_id,
                    t.base_quantity, t.base_unit_id,
                    NULL AS entered_quantity, NULL AS entered_unit_id,
                    NULL AS vendor_code, NULL AS vendor_id,
                    NULL AS par_qty, NULL AS par_unit_id, NULL AS par_base_qty,
                    NULL AS order_qty, NULL AS order_unit_id,
                    NULL AS original_quantity, NULL AS corrected_by, NULL AS corrected_at,
                    NULL AS correction_notes, NULL AS entered_by,
                    p.name   AS product_name,
                    cat.name AS category,
                    u.name   AS base_unit,
                    NULL AS vendor_name, NULL AS order_unit, NULL AS par_unit,
                    FALSE AS is_day_count
                FROM (
                    SELECT e.product_id,
                           SUM(e.base_quantity) AS base_quantity,
                           MAX(e.base_unit_id)  AS base_unit_id
                    FROM inventory_count_entries e
                    WHERE e.inventory_submission_id = :id AND e.superseded_at IS NULL
                    GROUP BY e.product_id
                ) t
                JOIN products p                  ON t.product_id   = p.id
                LEFT JOIN product_categories cat ON p.category_id  = cat.id
                LEFT JOIN units u                ON t.base_unit_id = u.id
                ORDER BY cat.name, p.name
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


@bp.route('/inventory-submissions/<int:submission_id>/products/<int:product_id>', methods=['PUT'])
@gm_or_admin_required
def correct_inventory_product(submission_id, product_id):
    """
    Admin/GM correct one product's count on a submitted inventory.
    Body: {quantity, unit_id, correction_notes}  (correct in any unit with a conversion)
       or {base_quantity, correction_notes}      (correct directly in base units)

    The old lines are kept as history, the first value stays in original_quantity,
    and the day's count follows only if this inventory is the one holding it.
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
        quantity = round(float(quantity), 4)
    except (TypeError, ValueError):
        return jsonify({'error': 'quantity must be a number'}), 400
    if quantity < 0:
        return jsonify({'error': 'quantity cannot be negative'}), 400

    user = g.user.get('email')
    try:
        with get_engine().begin() as conn:
            sub = _load_submission_for_user(conn, submission_id)
            adopt_day_counts(conn, sub.location_id, sub.count_date)

            row = conn.execute(text("""
                SELECT c.base_unit_id, p.base_unit_id AS product_base_unit_id
                FROM inventory_submission_counts c
                JOIN products p ON p.id = c.product_id
                WHERE c.inventory_submission_id = :sid AND c.product_id = :pid
            """), {'sid': submission_id, 'pid': product_id}).fetchone()
            if not row:
                return jsonify({'error': 'Count not found on this inventory'}), 404

            if unit_id is None:
                # Straight base-unit correction: stay in the unit this count was stored in.
                base_unit_id = row.base_unit_id or row.product_base_unit_id
                unit_id      = base_unit_id
                base_qty     = quantity
            else:
                unit_id = int(unit_id)
                base_qty, base_unit_id = _to_base(conn, product_id, unit_id, quantity)
                if base_qty is None:
                    return jsonify({'error': 'This unit has no conversion to the product\'s base unit'}), 400

            replace_product_lines(conn, submission_id, product_id, [{
                'product_id':    product_id,
                'unit_id':       unit_id,
                'quantity':      quantity,
                'base_quantity': base_qty,
                'base_unit_id':  base_unit_id,
            }], user)
            sync_counts_from_entries(conn, submission_id, user, [product_id],
                                     mark_changes=True,
                                     correction_notes=data.get('correction_notes'))
            refresh_day_counts(conn, sub.location_id, sub.count_date, [product_id])
        return jsonify({'status': 'ok', 'base_quantity': base_qty})
    except AccessError:
        raise
    except Exception as e:
        logger.error(f'correct_inventory_product: {e}')
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
    Turn the page's entries into {(product_id, unit_id): quantity_or_None}.

    One entry is one box on the sheet. A number sets that line; quantity null
    means the box was cleared and the line is removed. Boxes the page does not
    mention are left alone. A product can sit in two template sections, so the
    same box may arrive twice; a number always beats a blank.
    Raises ValueError with a message the user can read.
    """
    lines = {}
    for e in raw_entries or []:
        pid, uid = e.get('product_id'), e.get('unit_id')
        if not pid or not uid:
            continue
        key = (int(pid), int(uid))
        qty = e.get('quantity')
        if qty is None or qty == '':
            if 'quantity' in e:
                lines.setdefault(key, None)      # cleared box
            continue
        try:
            q = round(float(qty), 4)             # counts are stored to 4 decimals
        except (TypeError, ValueError):
            raise ValueError(f'"{qty}" is not a number')
        if q < 0:
            raise ValueError('Counts cannot be negative')
        lines[key] = q
    return lines


@bp.route('/inventory-submissions/<int:submission_id>/save', methods=['PUT'])
@staff_required
def save_inventory_entries(submission_id):
    """
    Save counts, box by box.

    Every line is converted to the product's base unit (read from products, not
    from the page). A line whose unit has no conversion is refused and nothing
    is saved. Changed lines are kept as history.

    Draft:     only the lines are saved. The day's count is not touched.
    Submitted: this inventory's product totals are rebuilt too, the change is
               recorded as a correction, and the day's count follows if this
               inventory is the one holding it.
    """
    data = request.get_json(force=True) or {}
    try:
        payload = _parse_entry_lines(data.get('entries'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    user = g.user.get('email')
    try:
        with get_engine().begin() as conn:
            sub = _load_submission_for_user(conn, submission_id)
            if not payload:
                return jsonify({'status': 'ok', 'saved': 0})

            product_ids = list({pid for pid, _ in payload})
            current = {
                (r.product_id, r.unit_id): float(r.quantity)
                for r in conn.execute(text("""
                    SELECT product_id, unit_id, quantity
                    FROM inventory_count_entries
                    WHERE inventory_submission_id = :sid AND superseded_at IS NULL
                      AND product_id = ANY(:pids)
                """), {'sid': submission_id, 'pids': product_ids}).fetchall()
            }

            # ── What actually changed ──────────────────────────────────────────
            to_remove = [k for k, q in payload.items() if q is None and k in current]
            to_write  = {k: q for k, q in payload.items()
                         if q is not None and current.get(k) != q}
            if not to_remove and not to_write:
                return jsonify({'status': 'ok', 'saved': 0})

            # ── Convert the lines being written; refuse if any cannot convert ──
            write_pids = {pid for pid, _ in to_write}
            base_units = load_base_units(conn, write_pids)
            conv_map   = load_conversion_map(conn, write_pids,
                                             {uid for _, uid in to_write},
                                             {b for b in base_units.values() if b})
            new_rows, missing = [], []
            for (pid, uid), q in to_write.items():
                factor = base_factor(conv_map, uid, base_units.get(pid), pid)
                if factor is None:
                    missing.append((pid, uid))
                    continue
                new_rows.append({
                    'product_id':    pid,
                    'unit_id':       uid,
                    'quantity':      q,
                    'base_quantity': q * factor,
                    'base_unit_id':  base_units[pid],
                })

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

            # ── Lines: retire the old ones, write the new ones ─────────────────
            retire = to_remove + [k for k in to_write if k in current]
            supersede_line_pairs(conn, submission_id, retire, user)
            insert_lines(conn, submission_id, new_rows, user)

            changed_pids = list({pid for pid, _ in to_remove} | write_pids)

            # ── Submitted inventory: its totals and the day's count follow ─────
            if sub.status == 'submitted':
                adopt_day_counts(conn, sub.location_id, sub.count_date)
                sync_counts_from_entries(conn, submission_id, user, changed_pids,
                                         mark_changes=True)
                refresh_day_counts(conn, sub.location_id, sub.count_date, changed_pids)

        return jsonify({'status': 'ok', 'saved': len(changed_pids)})
    except AccessError:
        raise
    except Exception as e:
        logger.error(f'save_inventory_entries: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-submissions/<int:submission_id>/submit', methods=['POST'])
@staff_required
def submit_inventory(submission_id):
    """
    Submit a manual inventory. This is the moment its counts start to matter:
    its product totals are built from the saved lines, and it becomes the day's
    count for every product it counted (latest submitted inventory wins).
    """
    user = g.user.get('email')
    try:
        with get_engine().begin() as conn:
            sub = _load_submission_for_user(conn, submission_id)
            if sub.status == 'submitted':
                return jsonify({'error': 'Already submitted'}), 400
            adopt_day_counts(conn, sub.location_id, sub.count_date)

            conn.execute(text("""
                UPDATE inventory_submissions SET
                    status       = 'submitted',
                    submitted_by = :submitted_by,
                    submitted_at = NOW(),
                    updated_at   = NOW()
                WHERE id = :id
            """), {'id': submission_id, 'submitted_by': user})

            sync_counts_from_entries(conn, submission_id, user, mark_changes=False)
            product_ids = _counted_product_ids(conn, submission_id)
            refresh_day_counts(conn, sub.location_id, sub.count_date, product_ids)

        return jsonify({'status': 'submitted', 'item_count': len(product_ids)})
    except AccessError:
        raise
    except Exception as e:
        logger.error(f'submit_inventory: {e}')
        return jsonify({'error': str(e)}), 500


def _counted_product_ids(conn, submission_id):
    """Products this inventory has a total for, plus any day's count it holds."""
    rows = conn.execute(text("""
        SELECT product_id FROM inventory_submission_counts WHERE inventory_submission_id = :id
        UNION
        SELECT product_id FROM inventory_counts WHERE inventory_submission_id = :id
    """), {'id': submission_id}).fetchall()
    return [r.product_id for r in rows]


@bp.route('/inventory-submissions/<int:submission_id>', methods=['DELETE'])
@gm_or_admin_required
def delete_inventory_submission(submission_id):
    """
    Delete an inventory with its lines and product totals.
    Each day's count it was holding goes back to the next most recent submitted
    inventory for that day, or is removed when there is none.
    """
    try:
        with get_engine().begin() as conn:
            sub = _load_submission_for_user(conn, submission_id)
            adopt_day_counts(conn, sub.location_id, sub.count_date)
            product_ids = _counted_product_ids(conn, submission_id)

            conn.execute(text("""
                DELETE FROM inventory_counts WHERE inventory_submission_id = :id
            """), {'id': submission_id})
            # Lines and product totals go with the header (ON DELETE CASCADE).
            conn.execute(text("""
                DELETE FROM inventory_submissions WHERE id = :id
            """), {'id': submission_id})

            refresh_day_counts(conn, sub.location_id, sub.count_date, product_ids)
        return jsonify({'status': 'ok'})
    except AccessError:
        raise
    except Exception as e:
        logger.error(f'delete_inventory_submission: {e}')
        return jsonify({'error': str(e)}), 500
