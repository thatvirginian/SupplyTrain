# =============================================================================
# backend/features/inventory/inventory_daily_routes.py
# =============================================================================
# The daily inventory: one store, one date, every product the store inventories,
# with the day's count (inventory_counts) and where it came from.
#
# Products listed = products on the store's inventory templates or order sheet
# templates, plus anything ever counted at the store.
#
# Amounts are stored in base units. Here each product is SHOWN in one chosen
# unit, converted with today's conversions:
#   products.inventory_unit_id, else the store's vendor order unit, else the
#   product's active vendor item order unit, else the base unit.
# If that unit has no conversion to a count's base unit, the count is shown in
# its base unit instead (never guessed).
#
# Endpoints in this file:
#   GET  /api/inventory/daily   get_daily_inventory
# =============================================================================

from datetime import date as date_cls
import logging

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from core.auth import staff_required, _is_admin, _get_user_location
from core.database import get_engine
from core.units import load_conversion_map, base_factor

logger = logging.getLogger(__name__)

bp = Blueprint('inventory_daily_routes', __name__, url_prefix='/api')


def _to_display(conv_map, base_qty, base_unit_id, display_unit_id, product_id):
    """
    Base quantity -> display unit with today's conversion.
    Returns (qty, unit_id, converted): converted is False when no conversion
    exists and the base amount is returned unchanged.
    """
    if base_qty is None:
        return None, None, False
    if display_unit_id is None or display_unit_id == base_unit_id:
        return float(base_qty), base_unit_id, True
    factor = base_factor(conv_map, display_unit_id, base_unit_id, product_id)   # 1 display = factor base
    if not factor:
        return float(base_qty), base_unit_id, False
    return float(base_qty) / factor, display_unit_id, True


@bp.route('/inventory/daily', methods=['GET'])
@staff_required
def get_daily_inventory():
    """
    Query params:
        location_id   admins only (others always see their own store)
        date          YYYY-MM-DD, default today (server date)
        category_id   optional
        vendor_id     optional (the store's vendor for the product)
        search        optional, product name contains
        counted_only  true = only products counted on that date
    """
    count_date   = request.args.get('date') or date_cls.today().isoformat()
    category_id  = request.args.get('category_id', type=int)
    vendor_id    = request.args.get('vendor_id', type=int)
    search       = (request.args.get('search') or '').strip()
    counted_only = (request.args.get('counted_only') or '').lower() == 'true'

    try:
        date_cls.fromisoformat(count_date)
    except ValueError:
        return jsonify({'error': 'date must be YYYY-MM-DD'}), 400

    with get_engine().connect() as conn:
        if _is_admin():
            location_id = request.args.get('location_id')
            if not location_id:
                return jsonify({'error': 'Choose a location'}), 400
        else:
            location_id = _get_user_location(conn)
            if not location_id:
                return jsonify({'error': 'No location is linked to your account'}), 403
        location_id = str(location_id)

        location = conn.execute(text("""
            SELECT store_guid::text AS location_id, location_name
            FROM locations WHERE store_guid::text = :loc
        """), {'loc': location_id}).mappings().fetchone()
        if not location:
            return jsonify({'error': 'Location not found'}), 404

        filters, params = [], {'loc': location_id, 'day': count_date}
        if category_id:
            filters.append('p.category_id = :category_id')
            params['category_id'] = category_id
        if vendor_id:
            filters.append('COALESCE(lvi_vi.vendor_id, vi.vendor_id) = :vendor_id')
            params['vendor_id'] = vendor_id
        if search:
            filters.append('p.name ILIKE :search')
            params['search'] = f'%{search}%'
        if counted_only:
            filters.append('d.id IS NOT NULL')
        where = ('AND ' + ' AND '.join(filters)) if filters else ''

        rows = conn.execute(text(f"""
            WITH store_products AS (
                -- On the store's inventory templates
                SELECT iti.product_id
                FROM inventory_template_locations itl
                JOIN inventory_templates it          ON it.id = itl.template_id AND it.active
                JOIN inventory_template_sections its ON its.template_id = it.id
                JOIN inventory_template_items iti    ON iti.section_id = its.id
                WHERE itl.location_id = :loc
                UNION
                -- On the store's order sheet templates
                SELECT ssi.product_id
                FROM sheet_template_locations stl
                JOIN sheet_templates st      ON st.id = stl.template_id AND st.active
                JOIN sheet_sections ss       ON ss.template_id = st.id
                JOIN sheet_section_items ssi ON ssi.section_id = ss.id
                WHERE stl.location_id = :loc
                UNION
                -- Counted at the store at any time
                SELECT DISTINCT product_id FROM inventory_counts WHERE location_id = :loc
            )
            SELECT
                p.id   AS product_id,
                p.name AS product_name,
                p.base_unit_id AS product_base_unit_id,
                cat.id   AS category_id,
                cat.name AS category,
                COALESCE(lvi_vi.vendor_id, vi.vendor_id) AS vendor_id,
                v.name   AS vendor_name,
                -- The unit to show: setting, store's order unit, active order unit, base
                COALESCE(p.inventory_unit_id, lvi_vi.order_unit_id, vi.order_unit_id, p.base_unit_id)
                         AS display_unit_id,
                CASE WHEN p.inventory_unit_id IS NOT NULL THEN 'product setting'
                     WHEN lvi_vi.order_unit_id IS NOT NULL THEN 'store order unit'
                     WHEN vi.order_unit_id IS NOT NULL THEN 'order unit'
                     ELSE 'base unit' END AS display_unit_source,

                -- The day's count
                d.base_quantity           AS day_base_quantity,
                d.base_unit_id            AS day_base_unit_id,
                d.inventory_submission_id AS day_inventory_id,
                d.entered_by              AS day_counted_by,
                ivs.source                AS day_source,
                ivs.submitted_at          AS day_submitted_at,
                COALESCE(it.name, st.name) AS day_template_name,
                (SELECT COUNT(*)
                   FROM inventory_submission_counts c2
                   JOIN inventory_submissions iv2 ON iv2.id = c2.inventory_submission_id
                  WHERE iv2.location_id = :loc AND iv2.count_date = CAST(:day AS date)
                    AND iv2.status = 'submitted' AND c2.product_id = p.id
                    AND iv2.id IS DISTINCT FROM d.inventory_submission_id) AS replaced_count,

                -- The last count before this date
                last.count_date    AS last_count_date,
                last.base_quantity AS last_base_quantity,
                last.base_unit_id  AS last_base_unit_id
            FROM store_products sp
            JOIN products p                  ON p.id = sp.product_id
            LEFT JOIN product_categories cat ON cat.id = p.category_id
            LEFT JOIN location_vendor_items lvi
                   ON lvi.product_id = p.id AND lvi.location_id = :loc AND lvi.active
            LEFT JOIN vendor_items lvi_vi    ON lvi_vi.id = lvi.vendor_item_id
            LEFT JOIN vendor_items vi        ON vi.product_id = p.id AND vi.active
            LEFT JOIN vendors v              ON v.id = COALESCE(lvi_vi.vendor_id, vi.vendor_id)
            LEFT JOIN inventory_counts d
                   ON d.location_id = :loc AND d.product_id = p.id AND d.count_date = CAST(:day AS date)
            LEFT JOIN inventory_submissions ivs ON ivs.id = d.inventory_submission_id
            LEFT JOIN inventory_templates it    ON it.id = ivs.template_id
            LEFT JOIN sheet_submissions ss      ON ss.id = ivs.sheet_submission_id
            LEFT JOIN sheet_templates st        ON st.id = ss.template_id
            LEFT JOIN LATERAL (
                SELECT ic.count_date, ic.base_quantity, ic.base_unit_id
                FROM inventory_counts ic
                WHERE ic.location_id = :loc AND ic.product_id = p.id
                  AND ic.count_date < CAST(:day AS date)
                ORDER BY ic.count_date DESC
                LIMIT 1
            ) last ON TRUE
            WHERE (p.active OR d.id IS NOT NULL)
            {where}
            ORDER BY cat.name NULLS LAST, p.name
        """), params).mappings().all()

        # Today's conversions, one query, for every unit that may be needed
        product_ids = {r['product_id'] for r in rows}
        display_ids = {r['display_unit_id'] for r in rows if r['display_unit_id']}
        base_ids    = {u for r in rows for u in (r['day_base_unit_id'], r['last_base_unit_id'],
                                                 r['product_base_unit_id']) if u}
        conv_map = load_conversion_map(conn, product_ids, display_ids, base_ids)

        unit_names = {
            u.id: u.name for u in conn.execute(text("""
                SELECT id, COALESCE(display, name) AS name FROM units WHERE id = ANY(:ids)
            """), {'ids': list(display_ids | base_ids) or [0]}).fetchall()
        }

    products = []
    for r in rows:
        day_qty, day_unit, day_ok = _to_display(
            conv_map, r['day_base_quantity'], r['day_base_unit_id'], r['display_unit_id'], r['product_id'])
        last_qty, last_unit, last_ok = _to_display(
            conv_map, r['last_base_quantity'], r['last_base_unit_id'], r['display_unit_id'], r['product_id'])
        products.append({
            'product_id':          r['product_id'],
            'product_name':        r['product_name'],
            'category_id':         r['category_id'],
            'category':            r['category'],
            'vendor_id':           r['vendor_id'],
            'vendor_name':         r['vendor_name'],
            'display_unit_id':     r['display_unit_id'],
            'display_unit':        unit_names.get(r['display_unit_id']),
            'display_unit_source': r['display_unit_source'],
            'counted':             r['day_inventory_id'] is not None or r['day_base_quantity'] is not None,
            'quantity':            day_qty,
            'unit':                unit_names.get(day_unit),
            'converted':           day_ok,
            'base_quantity':       float(r['day_base_quantity']) if r['day_base_quantity'] is not None else None,
            'base_unit':           unit_names.get(r['day_base_unit_id']),
            'inventory_id':        r['day_inventory_id'],
            'source':              r['day_source'],
            'template_name':       r['day_template_name'],
            'counted_by':          r['day_counted_by'],
            'submitted_at':        r['day_submitted_at'].isoformat() if hasattr(r['day_submitted_at'], 'isoformat')
                                   else r['day_submitted_at'],
            'replaced_count':      int(r['replaced_count'] or 0),
            'last_count_date':     r['last_count_date'].isoformat() if hasattr(r['last_count_date'], 'isoformat')
                                   else r['last_count_date'],
            'last_quantity':       last_qty,
            'last_unit':           unit_names.get(last_unit),
        })

    return jsonify({
        'location_id':   location['location_id'],
        'location_name': location['location_name'],
        'date':          count_date,
        'products':      products,
        'counted':       sum(1 for p in products if p['counted']),
    })
