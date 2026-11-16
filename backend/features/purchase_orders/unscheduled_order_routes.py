# =============================================================================
# backend/features/purchase_orders/unscheduled_order_routes.py
# =============================================================================
# Unscheduled Orders: a purchase order placed by hand with one vendor (usually
# the commissary), with no count and no inventory behind it. Typical use: a
# catering that needs product from the commissary on a given day.
#
# Once created it is an ordinary purchase order (order_type = 'unscheduled'):
# it shows in Order History, the commissary accepts / picks / ships it, the
# store fulfills it, all through purchase_order_routes.py.
#
# Endpoints in this file:
#   GET   /api/unscheduled-orders/vendors           list_order_vendors
#   GET   /api/unscheduled-orders/vendor-products   search_vendor_products
#   POST  /api/unscheduled-orders                   create_unscheduled_order
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
from datetime import date
import logging

from core.auth import (
    store_required, _is_admin, _get_user_location,
)
from core.database import get_engine
from core.units import (
    load_base_units, load_conversion_map, base_factor, load_unit_choices,
)

logger = logging.getLogger(__name__)

bp = Blueprint('unscheduled_order_routes', __name__, url_prefix='/api')

REASONS = ('catering', 'event', 'special', 'other')


def _resolve_location(conn, requested):
    """Admin may order for any location; everyone else orders for their own."""
    if _is_admin():
        return requested or None
    return _get_user_location(conn)


def _vendor_products(conn, vendor_id, location_id, search=None, product_ids=None, limit=25):
    """
    One row per product this vendor sells (its vendor items linked to a product).
    Inactive vendor items are included on purpose: only one vendor item per
    product may be active, so a product normally bought from PFG still has an
    inactive commissary item that is the right one to use here.
    Preference: the location's own vendor item, then active, then newest.
    """
    filters = ['vi.vendor_id = :vendor_id', 'vi.product_id IS NOT NULL', 'p.active = TRUE']
    params  = {'vendor_id': vendor_id, 'location_id': location_id, 'limit': limit}
    if search:
        filters.append('(p.name ILIKE :like OR vi.name ILIKE :like OR vi.vendor_code ILIKE :like)')
        params['like'] = f'%{search}%'
    if product_ids is not None:
        filters.append('p.id = ANY(:product_ids)')
        params['product_ids'] = list(product_ids)
        params['limit'] = max(limit, len(product_ids))

    rows = conn.execute(text(f"""
        SELECT * FROM (
            SELECT DISTINCT ON (p.id)
                p.id            AS product_id,
                p.name          AS product_name,
                p.base_unit_id,
                vi.id           AS vendor_item_id,
                vi.vendor_code,
                vi.packaging,
                vi.price,
                vi.order_unit_id,
                ou.name         AS order_unit,
                c.name          AS category_name
            FROM vendor_items vi
            JOIN products p                 ON p.id  = vi.product_id
            LEFT JOIN units ou              ON ou.id = vi.order_unit_id
            LEFT JOIN product_categories c  ON c.id  = p.category_id
            LEFT JOIN location_vendor_items lvi
                   ON lvi.product_id = p.id AND lvi.location_id = :location_id
            WHERE {' AND '.join(filters)}
            ORDER BY p.id,
                     (lvi.vendor_item_id = vi.id) DESC NULLS LAST,
                     vi.active DESC,
                     vi.id DESC
        ) x
        ORDER BY product_name
        LIMIT :limit
    """), params).mappings().all()
    return [dict(r) for r in rows]


def _with_units(conn, products):
    """Add 'units' (choices) and 'default_unit_id' (the vendor's order unit) to each row."""
    choices = load_unit_choices(conn, [p['product_id'] for p in products])
    for p in products:
        units = list(choices.get(p['product_id'], []))
        if p['order_unit_id'] and not any(u['id'] == p['order_unit_id'] for u in units):
            # The vendor's order unit is always allowed, even without a conversion
            # (base_quantity is then left empty, like Add Item does).
            units.insert(0, {'id': p['order_unit_id'], 'name': p['order_unit'], 'is_base': False})
        p['units'] = units
        p['default_unit_id'] = p['order_unit_id'] or p['base_unit_id']
    return products


# =============================================================================
# Pickers
# =============================================================================

@bp.route('/unscheduled-orders/vendors', methods=['GET'])
@store_required
def list_order_vendors():
    """Active vendors that sell at least one product. Commissary first."""
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT v.id, v.name, v.is_commissary
            FROM vendors v
            WHERE v.active = TRUE
              AND EXISTS (SELECT 1 FROM vendor_items vi
                          WHERE vi.vendor_id = v.id AND vi.product_id IS NOT NULL)
            ORDER BY v.is_commissary DESC, v.name
        """)).mappings().all()
    return jsonify([dict(r) for r in rows])


@bp.route('/unscheduled-orders/vendor-products', methods=['GET'])
@store_required
def search_vendor_products():
    """Products this vendor sells, matching ?search=, with the units they can be ordered in."""
    vendor_id = request.args.get('vendor_id', type=int)
    search    = (request.args.get('search') or '').strip()
    if not vendor_id:
        return jsonify({'error': 'vendor_id is required'}), 400
    with get_engine().connect() as conn:
        location_id = _resolve_location(conn, request.args.get('location_id'))
        products = _with_units(conn, _vendor_products(conn, vendor_id, location_id, search=search))
    return jsonify(products)


# =============================================================================
# Create
# =============================================================================

@bp.route('/unscheduled-orders', methods=['POST'])
@store_required
def create_unscheduled_order():
    """
    Body:
      location_id    admin only (everyone else orders for their own store)
      vendor_id      required
      expected_date  required (YYYY-MM-DD, the day it is needed)
      order_date     optional, default today
      reason         catering | event | special | other   (default catering)
      reference      optional free text (catering #, customer)
      notes          optional
      items          [{product_id, quantity, unit_id}]   at least one
    Creates one purchase order (status open, order_type unscheduled).
    """
    data      = request.get_json(force=True) or {}
    vendor_id = data.get('vendor_id')
    items     = data.get('items') or []
    reason    = data.get('reason') or 'catering'
    expected  = data.get('expected_date') or None
    order_dt  = data.get('order_date') or date.today().isoformat()

    if not vendor_id:
        return jsonify({'error': 'Pick a vendor'}), 400
    if not expected:
        return jsonify({'error': 'Pick the date the order is needed'}), 400
    if reason not in REASONS:
        return jsonify({'error': f'Unknown reason: {reason}'}), 400
    if not items:
        return jsonify({'error': 'Add at least one item'}), 400

    lines = []
    seen  = set()
    for raw in items:
        try:
            pid = int(raw.get('product_id'))
            qty = float(raw.get('quantity'))
            uid = int(raw['unit_id']) if raw.get('unit_id') else None
        except (TypeError, ValueError):
            return jsonify({'error': 'Every item needs a product and a number quantity'}), 400
        if qty <= 0:
            continue                         # blank / zero lines are dropped, not errors
        if pid in seen:
            return jsonify({'error': 'A product is listed twice; combine the lines'}), 400
        seen.add(pid)
        lines.append({'product_id': pid, 'quantity': qty, 'unit_id': uid})
    if not lines:
        return jsonify({'error': 'Every item has a quantity of zero'}), 400

    try:
        with get_engine().begin() as conn:
            location_id = _resolve_location(conn, data.get('location_id'))
            if not location_id:
                return jsonify({'error': 'Pick a location' if _is_admin()
                                else 'Your account is not linked to a location'}), 400

            vendor = conn.execute(text("""
                SELECT id, name, is_commissary FROM vendors WHERE id = :id AND active = TRUE
            """), {'id': vendor_id}).fetchone()
            if not vendor:
                return jsonify({'error': 'Vendor not found'}), 404

            catalog = {p['product_id']: p for p in _with_units(conn, _vendor_products(
                conn, vendor_id, location_id, product_ids=[l['product_id'] for l in lines]))}
            missing = [l['product_id'] for l in lines if l['product_id'] not in catalog]
            if missing:
                return jsonify({'error': f'{vendor.name} does not sell product(s) {missing}'}), 400

            # Units + base quantity
            pids       = [l['product_id'] for l in lines]
            base_units = load_base_units(conn, pids)
            conv_map   = load_conversion_map(
                conn, pids,
                {l['unit_id'] or catalog[l['product_id']]['default_unit_id'] for l in lines},
                set(base_units.values()))
            for l in lines:
                prod = catalog[l['product_id']]
                uid  = l['unit_id'] or prod['default_unit_id']
                if not any(u['id'] == uid for u in prod['units']):
                    return jsonify({'error': f"{prod['product_name']} cannot be ordered in that unit"}), 400
                f = base_factor(conv_map, uid, base_units.get(l['product_id']), l['product_id'])
                l['unit_id']       = uid
                l['base_unit_id']  = base_units.get(l['product_id'])
                l['base_quantity'] = round(l['quantity'] * f, 4) if f is not None else None

            po_id = conn.execute(text("""
                INSERT INTO purchase_orders (
                    location_id, order_date, expected_date, vendor_id, status,
                    created_by, is_commissary, order_type, reason, reference, notes
                ) VALUES (
                    :location_id, :order_date, :expected_date, :vendor_id, 'open',
                    :created_by, :is_commissary, 'unscheduled', :reason, :reference, :notes
                )
                RETURNING id
            """), {
                'location_id':   location_id,
                'order_date':    order_dt,
                'expected_date': expected,
                'vendor_id':     vendor.id,
                'created_by':    g.user.get('email'),
                'is_commissary': vendor.is_commissary,
                'reason':        reason,
                'reference':     (data.get('reference') or '').strip() or None,
                'notes':         (data.get('notes') or '').strip() or None,
            }).fetchone().id

            section_for = {}
            if vendor.is_commissary:
                section_for = _create_comm_sections(conn, po_id, location_id, vendor.id, pids)

            conn.execute(text("""
                INSERT INTO purchase_order_items (
                    purchase_order_id, product_id, vendor_item_id, vendor_code,
                    product_name, packaging, order_unit_id,
                    order_quantity, original_quantity,
                    base_quantity, base_unit_id, unit_price, total_price,
                    comm_section_id
                ) VALUES (
                    :po_id, :product_id, :vendor_item_id, :vendor_code,
                    :product_name, :packaging, :order_unit_id,
                    :qty, :qty,
                    :base_quantity, :base_unit_id, :unit_price, :total_price,
                    :comm_section_id
                )
            """), [{
                'po_id':           po_id,
                'product_id':      l['product_id'],
                'vendor_item_id':  catalog[l['product_id']]['vendor_item_id'],
                'vendor_code':     catalog[l['product_id']]['vendor_code'] or '',
                'product_name':    catalog[l['product_id']]['product_name'],
                'packaging':       catalog[l['product_id']]['packaging'],
                'order_unit_id':   l['unit_id'],
                'qty':             l['quantity'],
                'base_quantity':   l['base_quantity'],
                'base_unit_id':    l['base_unit_id'],
                # Price only applies when ordering in the vendor's own unit
                'unit_price':      catalog[l['product_id']]['price']
                                   if l['unit_id'] == catalog[l['product_id']]['order_unit_id'] else None,
                'total_price':     round(float(catalog[l['product_id']]['price']) * l['quantity'], 4)
                                   if catalog[l['product_id']]['price'] is not None
                                   and l['unit_id'] == catalog[l['product_id']]['order_unit_id'] else None,
                'comm_section_id': section_for.get(l['product_id']),
            } for l in lines])

        return jsonify({'id': po_id}), 201
    except Exception as e:
        logger.error(f'create_unscheduled_order: {e}')
        return jsonify({'error': str(e)}), 500


def _create_comm_sections(conn, po_id, location_id, vendor_id, product_ids):
    """
    Same sectioning as an order sheet's commissary order: the location's
    commissary template decides the section of each product, anything not on
    the template goes to 'Other'. Returns {product_id: comm_section_id}.
    """
    tmpl = conn.execute(text("""
        SELECT id FROM comm_order_templates
        WHERE location_id = :location_id AND vendor_id = :vendor_id AND active = TRUE
        LIMIT 1
    """), {'location_id': location_id, 'vendor_id': vendor_id}).fetchone()

    product_section, section_sort = {}, {}
    if tmpl:
        for r in conn.execute(text("""
            SELECT s.name, s.sort_order, i.product_id
            FROM comm_order_template_sections s
            LEFT JOIN comm_order_template_items i ON i.section_id = s.id
            WHERE s.template_id = :tid
        """), {'tid': tmpl.id}).fetchall():
            section_sort[r.name] = r.sort_order
            if r.product_id:
                product_section[r.product_id] = r.name

    needed = {}
    for pid in product_ids:
        name = product_section.get(pid, 'Other')
        needed[name] = section_sort.get(name, 999)

    ids = {}
    for name, sort in sorted(needed.items(), key=lambda x: x[1]):
        ids[name] = conn.execute(text("""
            INSERT INTO comm_order_sections (purchase_order_id, name, sort_order)
            VALUES (:po_id, :name, :sort) RETURNING id
        """), {'po_id': po_id, 'name': name, 'sort': sort}).fetchone().id

    return {pid: ids[product_section.get(pid, 'Other')] for pid in product_ids}
