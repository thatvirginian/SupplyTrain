# =============================================================================
# backend/features/usage/usage_routes.py
# =============================================================================
# Actual usage for one store, count to count.
#
# A WINDOW is the time between two counts of a product (counts are end of
# day, ~9pm). For each product and window:
#
#   actual  = start count + received + transfers in - transfers out - end count
#   extra   = what extra (unscheduled) orders delivered, for events in the window
#   regular = actual - extra
#
#   received        every received order line (regular AND extra orders), dated
#                   by when the order was received (store's local date).
#                   'received' = the line's base quantity, 'returned' = 0.
#   extra           received lines of unscheduled orders, dated by the order's
#                   needed-by date (the event), else its received date. Extra
#                   orders are in-and-out: they come in as received and are
#                   taken out again to get regular usage.
#   transfers in    received transfers, received_base_quantity, received date
#   transfers out   sent transfers (sent or received), base_quantity, sent date
#
# A delivery received on day D belongs to the window (start, end] that holds D:
# received the same day as the start count -> it was in that count already.
#
# Windows come from each product's own counts, so a product skipped on one
# count gets one longer window (still correct usage). A window "fits the
# schedule" when its start and end are consecutive order sheet days (the
# store's ordering rhythm; any count day if it has none). Only those feed
# the normal usage per order day (median regular of the last 4).
#
# All amounts are base quantities. Each stored amount is converted from its
# own base unit to the product's current base unit with today's conversions;
# anything that cannot be converted is left out and flagged, never guessed.
#
# Endpoints in this file:
#   GET  /api/usage   get_usage
# =============================================================================

from datetime import date, timedelta
from statistics import median
import logging
import os

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from core.auth import manage_required, _is_admin, _get_user_location
from core.database import get_engine
from core.units import load_conversion_map, base_factor

logger = logging.getLogger(__name__)

bp = Blueprint('usage_routes', __name__, url_prefix='/api')

# Receipts and transfers are dated in the stores' local time (counts are by
# local date). One setting for now; per-location later if stores span zones.
STORE_TZ = os.environ.get('STORE_TIMEZONE', 'America/New_York')

LOOKBACK_DAYS = 60       # how far before date_from to look for each product's start count
WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def _d(v):
    """date / 'YYYY-MM-DD' / timestamp string -> date"""
    if v is None:
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _f(v):
    return float(v) if v is not None else None


@bp.route('/usage', methods=['GET'])
@manage_required
def get_usage():
    """
    Query params:
        location_id   admin only (managers see their own store)
        date_from     YYYY-MM-DD  windows ENDING on or after this day (default 28 days ago)
        date_to       YYYY-MM-DD  windows ending on or before this day (default today)
        search        product name contains
        category_id   optional
    """
    try:
        date_to   = date.fromisoformat(request.args.get('date_to') or date.today().isoformat())
        date_from = date.fromisoformat(request.args.get('date_from') or (date_to - timedelta(days=28)).isoformat())
    except ValueError:
        return jsonify({'error': 'Dates must be YYYY-MM-DD'}), 400
    if date_from > date_to:
        return jsonify({'error': 'From date is after To date'}), 400
    search      = (request.args.get('search') or '').strip()
    category_id = request.args.get('category_id', type=int)

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

        look_from = date_from - timedelta(days=LOOKBACK_DAYS)
        params = {'loc': location_id, 'look_from': look_from, 'to': date_to, 'tz': STORE_TZ}

        # ── Products + their counts ─────────────────────────────────────────
        pfilters = []
        if search:
            pfilters.append('p.name ILIKE :search')
            params['search'] = f'%{search}%'
        if category_id:
            pfilters.append('p.category_id = :category_id')
            params['category_id'] = category_id
        pwhere = ('AND ' + ' AND '.join(pfilters)) if pfilters else ''

        counts = conn.execute(text(f"""
            SELECT ic.product_id, ic.count_date, ic.base_quantity, ic.base_unit_id,
                   ic.inventory_submission_id
            FROM inventory_counts ic
            JOIN products p ON p.id = ic.product_id
            WHERE ic.location_id = :loc
              AND ic.count_date BETWEEN CAST(:look_from AS date) AND CAST(:to AS date)
              AND ic.base_quantity IS NOT NULL
              {pwhere}
            ORDER BY ic.product_id, ic.count_date
        """), params).mappings().all()

        # Schedule days = days the store submitted an order sheet (its ordering
        # rhythm). A small manual count mid-week is not a schedule day. Stores
        # with no order sheets: every count day.
        store_days = sorted({_d(r['count_date']) for r in conn.execute(text("""
            SELECT DISTINCT count_date FROM inventory_submissions
            WHERE location_id = :loc AND status = 'submitted' AND source = 'count_sheet'
              AND count_date BETWEEN CAST(:look_from AS date) AND CAST(:to AS date)
        """), params).mappings().all()})
        if not store_days:
            store_days = sorted({_d(r['count_date']) for r in conn.execute(text("""
                SELECT DISTINCT count_date FROM inventory_counts
                WHERE location_id = :loc
                  AND count_date BETWEEN CAST(:look_from AS date) AND CAST(:to AS date)
            """), params).mappings().all()})

        product_ids = sorted({r['product_id'] for r in counts})
        if not product_ids:
            return jsonify(_empty(location, date_from, date_to, store_days))
        params['pids'] = product_ids

        products = {r['id']: dict(r) for r in conn.execute(text("""
            SELECT p.id, p.name, p.base_unit_id, p.category_id, cat.name AS category,
                   COALESCE(p.inventory_unit_id, lvi_vi.order_unit_id, vi.order_unit_id, p.base_unit_id)
                       AS display_unit_id
            FROM products p
            LEFT JOIN product_categories cat ON cat.id = p.category_id
            LEFT JOIN location_vendor_items lvi
                   ON lvi.product_id = p.id AND lvi.location_id = :loc AND lvi.active
            LEFT JOIN vendor_items lvi_vi ON lvi_vi.id = lvi.vendor_item_id
            LEFT JOIN vendor_items vi     ON vi.product_id = p.id AND vi.active
            WHERE p.id = ANY(:pids)
        """), params).mappings().all()}

        # ── Movements (from the earliest possible window start) ─────────────
        receipts = conn.execute(text("""
            SELECT poi.product_id, poi.base_quantity, poi.base_unit_id, poi.received_status,
                   po.id AS order_id, po.order_type, po.reason, po.reference,
                   v.name AS vendor_name,
                   (COALESCE(po.received_at, poi.received_at) AT TIME ZONE :tz)::date AS received_day,
                   po.expected_date
            FROM purchase_order_items poi
            JOIN purchase_orders po ON po.id = poi.purchase_order_id
            JOIN vendors v          ON v.id  = po.vendor_id
            WHERE po.location_id = :loc
              AND poi.product_id = ANY(:pids)
              AND poi.received_status IN ('received', 'returned')
              AND COALESCE(po.received_at, poi.received_at) IS NOT NULL
              AND po.status <> 'cancelled'
              AND (COALESCE(po.received_at, poi.received_at) AT TIME ZONE :tz)::date
                  BETWEEN CAST(:look_from AS date) AND CAST(:to AS date) + 7
        """), params).mappings().all()

        transfers = conn.execute(text("""
            SELECT ti.product_id, t.id AS transfer_id,
                   CASE WHEN t.to_location_id = :loc THEN 'in' ELSE 'out' END AS direction,
                   ti.base_quantity, ti.base_unit_id,
                   ti.received_base_quantity, ti.received_base_unit_id,
                   (t.sent_at     AT TIME ZONE :tz)::date AS sent_day,
                   (t.received_at AT TIME ZONE :tz)::date AS received_day,
                   lo.location_name AS other_location
            FROM transfer_items ti
            JOIN transfers t ON t.id = ti.transfer_id
            LEFT JOIN locations lo ON lo.store_guid::text =
                 CASE WHEN t.to_location_id = :loc THEN t.from_location_id ELSE t.to_location_id END
            WHERE ti.product_id = ANY(:pids)
              AND (   (t.to_location_id   = :loc AND t.status = 'received')
                   OR (t.from_location_id = :loc AND t.status IN ('sent', 'received')))
        """), params).mappings().all()

        # Orders delivered (shipped) but not yet received: usage is incomplete
        pending = conn.execute(text("""
            SELECT po.id, po.expected_date, v.name AS vendor_name
            FROM purchase_orders po JOIN vendors v ON v.id = po.vendor_id
            WHERE po.location_id = :loc AND po.status = 'shipped'
              AND COALESCE(po.expected_date, po.order_date) <= CAST(:to AS date)
            ORDER BY po.expected_date
        """), params).mappings().all()

        # Conversions: every unit any stored amount is in -> product base units
        unit_ids = {r['base_unit_id'] for r in counts} \
                 | {r['base_unit_id'] for r in receipts} \
                 | {u for r in transfers for u in (r['base_unit_id'], r['received_base_unit_id'])} \
                 | {p['display_unit_id'] for p in products.values()}
        unit_ids.discard(None)
        base_ids = {p['base_unit_id'] for p in products.values()}
        conv_map = load_conversion_map(conn, product_ids, unit_ids, base_ids)
        unit_names = {u.id: u.name for u in conn.execute(text(
            "SELECT id, name FROM units WHERE id = ANY(:ids)"),
            {'ids': list(unit_ids | base_ids) or [0]}).fetchall()}

    # ── Build windows per product ───────────────────────────────────────────
    def to_base(qty, unit_id, pid):
        """stored amount -> product's current base unit; None if it cannot convert"""
        if qty is None:
            return None
        f = base_factor(conv_map, unit_id, products[pid]['base_unit_id'], pid)
        return None if f is None else float(qty) * f

    store_next = {store_days[i]: store_days[i + 1] for i in range(len(store_days) - 1)}

    by_pid = {}
    for r in counts:
        by_pid.setdefault(r['product_id'], []).append(r)
    rec_by_pid, tr_by_pid = {}, {}
    for r in receipts:
        rec_by_pid.setdefault(r['product_id'], []).append(r)
    for r in transfers:
        tr_by_pid.setdefault(r['product_id'], []).append(r)

    out = []
    for pid, plist in by_pid.items():
        p = products[pid]
        windows = []
        for a, b in zip(plist, plist[1:]):
            start_day, end_day = _d(a['count_date']), _d(b['count_date'])
            if not (date_from <= end_day <= date_to):
                continue
            w = _window(pid, a, b, start_day, end_day, rec_by_pid.get(pid, []),
                        tr_by_pid.get(pid, []), to_base, store_next)
            windows.append(w)
        if not windows:
            continue

        # Normal usage per order day: median regular of the last 4 schedule windows
        normal = {}
        for w in sorted(windows, key=lambda x: x['start_date'], reverse=True):
            if not w['fits_schedule'] or w['regular'] is None:
                continue
            day = WEEKDAYS[_d(w['start_date']).weekday()]
            normal.setdefault(day, [])
            if len(normal[day]) < 4:
                normal[day].append(w['regular'])
        normal_out = [{
            'order_day': day,
            'median_regular': round(median(vals), 4),
            'windows': len(vals),
        } for day, vals in sorted(normal.items(), key=lambda kv: WEEKDAYS.index(kv[0]))]

        disp_f = base_factor(conv_map, p['display_unit_id'], p['base_unit_id'], pid)
        tot = lambda k: round(sum(w[k] for w in windows if w[k] is not None), 4)
        out.append({
            'product_id':      pid,
            'product_name':    p['name'],
            'category_id':     p['category_id'],
            'category':        p['category'],
            'base_unit':       unit_names.get(p['base_unit_id']),
            'display_unit':    unit_names.get(p['display_unit_id']) if disp_f else unit_names.get(p['base_unit_id']),
            'display_factor':  disp_f or 1.0,          # 1 display unit = this many base units
            'totals': {
                'actual':  tot('actual'),
                'extra':   tot('extra'),
                'regular': tot('regular'),
            },
            'normal_by_order_day': normal_out,
            # Things to check (a skipped count is not one: its usage is still right)
            'flag_count':      sum(1 for w in windows for f in w['flags'] if f['code'] != 'off_schedule'),
            'windows':         sorted(windows, key=lambda x: x['end_date'], reverse=True),
        })

    out.sort(key=lambda x: ((x['category'] or '~'), x['product_name']))
    return jsonify({
        'location_id':    location['location_id'],
        'location_name':  location['location_name'],
        'date_from':      date_from.isoformat(),
        'date_to':        date_to.isoformat(),
        'timezone':       STORE_TZ,
        'store_count_days': [d.isoformat() for d in store_days if date_from - timedelta(days=7) <= d <= date_to],
        'pending_orders': [{'id': r['id'], 'vendor_name': r['vendor_name'],
                            'expected_date': str(r['expected_date'])[:10] if r['expected_date'] else None}
                           for r in pending],
        'products':       out,
    })


def _window(pid, a, b, start_day, end_day, receipts, transfers, to_base, store_next):
    """One product, one count-to-count window."""
    flags, sources = [], []

    def inside(day):
        return day is not None and start_day < day <= end_day

    start = to_base(a['base_quantity'], a['base_unit_id'], pid)
    end   = to_base(b['base_quantity'], b['base_unit_id'], pid)
    if start is None or end is None:
        flags.append({'code': 'count_unconverted',
                      'text': "A count is in a unit that no longer converts to the product's base unit"})

    received = extra = t_in = t_out = 0.0
    for r in receipts:
        rday = _d(r['received_day'])
        qty  = 0.0 if r['received_status'] == 'returned' else to_base(r['base_quantity'], r['base_unit_id'], pid)
        is_extra = r['order_type'] == 'unscheduled'
        in_recv  = inside(rday)
        # Extra orders come out of regular usage in the window of their event
        eday     = _d(r['expected_date']) or rday
        in_extra = is_extra and inside(eday)
        if not (in_recv or in_extra):
            continue
        if qty is None:
            flags.append({'code': 'receipt_unconverted',
                          'text': f"Order #{r['order_id']}: received line has no base quantity (left out)"})
            continue
        label = f"{r['vendor_name']} order #{r['order_id']}"
        if is_extra:
            label += f" · extra ({r['reason'] or 'other'})" + (f" · {r['reference']}" if r['reference'] else '')
        if in_recv:
            received += qty
            sources.append({'type': 'order', 'id': r['order_id'], 'date': rday.isoformat(),
                            'label': label + (' · returned' if r['received_status'] == 'returned' else ''),
                            'base_quantity': round(qty, 4), 'counts_as': 'received'})
        if in_extra:
            extra += qty
            sources.append({'type': 'order', 'id': r['order_id'], 'date': eday.isoformat(),
                            'label': label + ' · needed by', 'base_quantity': round(qty, 4),
                            'counts_as': 'extra'})

    for t in transfers:
        if t['direction'] == 'in':
            day, qty = _d(t['received_day']), to_base(t['received_base_quantity'], t['received_base_unit_id'], pid)
        else:
            day, qty = _d(t['sent_day']), to_base(t['base_quantity'], t['base_unit_id'], pid)
        if not inside(day):
            continue
        if qty is None:
            flags.append({'code': 'transfer_unconverted',
                          'text': f"Transfer #{t['transfer_id']}: amount has no base quantity (left out)"})
            continue
        if t['direction'] == 'in':
            t_in += qty
        else:
            t_out += qty
        sources.append({'type': 'transfer', 'id': t['transfer_id'], 'date': day.isoformat(),
                        'label': f"Transfer {'from' if t['direction'] == 'in' else 'to'} {t['other_location']}",
                        'base_quantity': round(qty, 4), 'counts_as': f"transfer_{t['direction']}"})

    actual = regular = None
    if start is not None and end is not None:
        actual  = round(start + received + t_in - t_out - end, 4)
        regular = round(actual - extra, 4)
        if actual < 0:
            flags.append({'code': 'negative_actual',
                          'text': 'More on hand than counted + received: a miscount or a receipt missing'})
        elif regular < 0:
            flags.append({'code': 'negative_regular',
                          'text': 'Extra orders delivered more than was used: catering leftover or a miscount'})

    fits = store_next.get(start_day) == end_day
    if not fits:
        flags.append({'code': 'off_schedule',
                      'text': 'Not counted on every count day in between: correct usage, but not used for the normal per order day'})

    return {
        'start_date':    start_day.isoformat(),
        'end_date':      end_day.isoformat(),
        'order_day':     WEEKDAYS[start_day.weekday()],
        'days':          (end_day - start_day).days,
        'fits_schedule': fits,
        'start':         round(start, 4) if start is not None else None,
        'start_inventory_id': a['inventory_submission_id'],
        'received':      round(received, 4),
        'transfers_in':  round(t_in, 4),
        'transfers_out': round(t_out, 4),
        'end':           round(end, 4) if end is not None else None,
        'end_inventory_id': b['inventory_submission_id'],
        'actual':        actual,
        'extra':         round(extra, 4),
        'regular':       regular,
        'flags':         flags,
        'sources':       sorted(sources, key=lambda s: s['date']),
    }


def _empty(location, date_from, date_to, store_days):
    return {
        'location_id':      location['location_id'],
        'location_name':    location['location_name'],
        'date_from':        date_from.isoformat(),
        'date_to':          date_to.isoformat(),
        'timezone':         STORE_TZ,
        'store_count_days': [d.isoformat() for d in store_days],
        'pending_orders':   [],
        'products':         [],
    }
