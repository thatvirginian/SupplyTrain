# =============================================================================
# backend/features/commissary/production_plan_routes.py
# =============================================================================
# Production Plan (commissary): what the stores have and what they ordered,
# laid out on a production template, so the commissary knows what to make.
# It replaces the paper "Daily Prep Production" sheet.
#
# One plan = one commissary + one production template + one date.
#   Rows     the template's products (its sections and order), shown in the
#            template's unit.
#   Columns  every store with a commissary order DELIVERED on that date
#            (purchase_orders.expected_date = date), sorted by route then name.
#            Commissary locations are never columns: a commissary does not
#            plan for its own orders.
#   Per store and product:
#     INV  what the store counted on the order sheet behind the order
#          (purchase_order_items.on_hand, base units). When a store has several
#          orders that day, the latest order with a count wins.
#     ORD  what the store ordered (original_quantity, before any commissary
#          change), summed over the store's orders that day.
#   Totals per product: INV and ORD over all stores.
#   Comm Inv  the commissary's own latest count BEFORE the plan date
#             (inventory_counts, any source: a production run's End Inv or a
#             commissary inventory), with the date it was counted.
#   What was made and the End Inv are entered on production runs, not here.
#
# Read only. Cancelled orders are left out. Any commissary order counts (there
# is no link yet between a commissary vendor and a commissary location; with
# one commissary that is the same thing).
#
# Endpoints in this file:
#   GET  /api/production-plan     production_plan
#        params: template_id, date (default today), location_id (admins)
# =============================================================================

from datetime import datetime
import os
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from core.auth import comm_required
from core.database import get_engine
from core.units import load_conversion_map, base_factor
from features.commissary.commissary_access import (
    CommissaryAccessError, resolve_commissary_location,
)
from features.commissary.production_template_routes import load_production_template

bp = Blueprint('production_plan_routes', __name__, url_prefix='/api')

STORE_TZ = os.environ.get('STORE_TIMEZONE', 'America/New_York')


def _today_local():
    return datetime.now(ZoneInfo(STORE_TZ)).date().isoformat()


def _num(v):
    return None if v is None else float(v)


@bp.route('/production-plan', methods=['GET'])
@comm_required
def production_plan():
    template_id = request.args.get('template_id', type=int)
    plan_date   = request.args.get('date') or _today_local()
    if not template_id:
        return jsonify({'error': 'template_id is required'}), 400
    try:
        datetime.strptime(plan_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Bad date'}), 400

    try:
        with get_engine().connect() as conn:
            location_id = resolve_commissary_location(conn, request.args.get('location_id'))

            assigned = conn.execute(text("""
                SELECT 1 FROM production_template_locations
                WHERE template_id = :tid AND location_id = :lid
            """), {'tid': template_id, 'lid': location_id}).fetchone()
            if not assigned:
                return jsonify({'error': 'That production template is not assigned to this commissary'}), 400

            template = load_production_template(conn, template_id)
            if not template:
                return jsonify({'error': 'Template not found'}), 404

            items = [i for s in template['sections'] for i in s['items']]
            product_ids = list({i['product_id'] for i in items})

            # Store orders delivered on the date (never a commissary's own)
            lines = conn.execute(text("""
                SELECT po.id AS order_id, po.location_id, po.status, po.created_at,
                       l.location_name, l.abbreviation, l.route,
                       poi.product_id,
                       COALESCE(poi.original_quantity, poi.order_quantity) AS ordered,
                       poi.order_unit_id,
                       poi.on_hand, poi.on_hand_unit_id
                FROM purchase_orders po
                JOIN purchase_order_items poi ON poi.purchase_order_id = po.id
                LEFT JOIN locations l ON l.store_guid::text = po.location_id::text
                WHERE po.is_commissary = TRUE
                  AND po.expected_date = CAST(:d AS date)
                  AND po.status <> 'cancelled'
                  AND po.location_id::text <> :lid
                  AND COALESCE(l.is_commissary, FALSE) = FALSE
                  AND poi.product_id = ANY(:pids)
                ORDER BY po.created_at, po.id
            """), {'d': plan_date, 'lid': location_id,
                   'pids': product_ids or [0]}).mappings().all()

            # Stores with any commissary order that day (even with none of these products)
            stores_rows = conn.execute(text("""
                SELECT po.location_id::text AS location_id, l.location_name, l.abbreviation, l.route,
                       array_agg(DISTINCT po.id)     AS order_ids,
                       array_agg(DISTINCT po.status) AS statuses
                FROM purchase_orders po
                LEFT JOIN locations l ON l.store_guid::text = po.location_id::text
                WHERE po.is_commissary = TRUE
                  AND po.expected_date = CAST(:d AS date)
                  AND po.status <> 'cancelled'
                  AND po.location_id::text <> :lid
                  AND COALESCE(l.is_commissary, FALSE) = FALSE
                GROUP BY po.location_id, l.location_name, l.abbreviation, l.route
            """), {'d': plan_date, 'lid': location_id}).mappings().all()

            # The commissary's latest count before the plan date, per product
            comm_inv = {r.product_id: (_num(r.base_quantity), r.base_unit_id, str(r.count_date)) for r in conn.execute(text("""
                SELECT DISTINCT ON (product_id) product_id, base_quantity, base_unit_id, count_date
                FROM inventory_counts
                WHERE location_id = :lid AND count_date < CAST(:d AS date)
                  AND product_id = ANY(:pids) AND base_quantity IS NOT NULL
                ORDER BY product_id, count_date DESC
            """), {'lid': location_id, 'd': plan_date, 'pids': product_ids or [0]}).fetchall()}

            base_units = {i['product_id']: i['base_unit_id'] for i in items}
            unit_ids = ({i['unit_id'] for i in items}
                        | {r['order_unit_id'] for r in lines} | {r['on_hand_unit_id'] for r in lines}
                        | {v[1] for v in comm_inv.values()})
            unit_ids.discard(None)
            conv = load_conversion_map(conn, product_ids, unit_ids,
                                       {b for b in base_units.values() if b})
    except CommissaryAccessError as e:
        return jsonify({'error': str(e)}), e.status

    def to_base(qty, unit_id, pid):
        if qty is None:
            return None
        f = base_factor(conv, unit_id, base_units.get(pid), pid)
        return None if f is None else float(qty) * f

    # Per store and product: inv (latest order with a count) and ord (sum)
    cells = {}          # (location_id, product_id) -> {'inv', 'ord', 'missing'}
    for r in lines:
        key = (str(r['location_id']), r['product_id'])
        c = cells.setdefault(key, {'inv': None, 'ord': 0.0, 'missing': False})
        o = to_base(r['ordered'], r['order_unit_id'], r['product_id'])
        if r['ordered'] is not None and o is None:
            c['missing'] = True
        elif o is not None:
            c['ord'] += o
        if r['on_hand'] is not None:
            inv = to_base(r['on_hand'], r['on_hand_unit_id'], r['product_id'])
            if inv is None:
                c['missing'] = True
            else:
                c['inv'] = inv          # later orders replace earlier ones

    stores = sorted(
        [{'location_id':   s['location_id'],
          'location_name': s['location_name'] or s['location_id'],
          'abbreviation':  s['abbreviation'],
          'route':         s['route'],
          'order_ids':     sorted(s['order_ids']),
          'statuses':      sorted(s['statuses'])} for s in stores_rows],
        key=lambda s: ((s['route'] or '~').lower(), (s['abbreviation'] or s['location_name'] or '').lower()))

    def shown(base_qty, item):
        """Base amount in the template's unit (None when it cannot convert)."""
        if base_qty is None:
            return None
        f = base_factor(conv, item['unit_id'], item['base_unit_id'], item['product_id'])
        return None if not f else round(base_qty / f, 2)

    sections = []
    for s in template['sections']:
        rows = []
        for i in s['items']:
            per_store = {}
            tot_inv = tot_ord = 0.0
            any_inv = any_ord = False
            missing = False
            for st in stores:
                c = cells.get((st['location_id'], i['product_id']))
                if not c:
                    continue
                inv, ord_ = shown(c['inv'], i), shown(c['ord'], i)
                if c['missing'] or (c['inv'] is not None and inv is None):
                    missing = True
                per_store[st['location_id']] = {'inv': inv, 'ord': ord_}
                if inv is not None:
                    tot_inv += inv; any_inv = True
                if ord_ is not None:
                    tot_ord += ord_; any_ord = True
            comm_qty = comm_date = None
            ci = comm_inv.get(i['product_id'])
            if ci:
                comm_date = ci[2]
                comm_qty = shown(to_base(ci[0], ci[1], i['product_id']), i)
                if comm_qty is None:
                    missing = True
            rows.append({
                'product_id':   i['product_id'],
                'product_name': i['product_name'],
                'unit_id':      i['unit_id'],
                'unit_name':    i['unit_name'],
                'stores':       per_store,
                'total_inv':    round(tot_inv, 2) if any_inv else None,
                'total_ord':    round(tot_ord, 2) if any_ord else None,
                'comm_inv':     comm_qty,
                'comm_inv_date': comm_date,
                'missing_conversion': missing,
            })
        sections.append({'id': s['id'], 'name': s['name'], 'items': rows})

    return jsonify({
        'location_id':   location_id,
        'date':          plan_date,
        'template_id':   template_id,
        'template_name': template['name'],
        'stores':        stores,
        'sections':      sections,
    })
