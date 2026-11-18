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
# WHICH COUNTS make the windows (?source=):
#   oh   order sheets only (default): windows run from one order sheet that
#        counted the product to the next one. A product on the sheet once a
#        week gets weekly windows; three times a week, three windows.
#   inv  standalone inventories only (no order sheet)
#   all  the day's count, whatever it came from (inventory_counts)
# For oh / inv each day uses that source's latest submitted count.
#
# A window is labelled by the days it COVERS: counts are end of day, so the
# Monday count to the Wednesday count covers Tue -> Wed. The ORDER DAY is
# the start count's day (the Monday order covers Tue -> Wed).
#
# Each product's windows come from its own counts, on its CURRENT count days
# (weekdays it was counted on in at least 2 of the last 3 weeks). History is
# re-cut to those days: counts on other days are skipped, which joins their
# windows into one wider window with exactly the same usage (the counts in
# between cancel out). So when a product goes from 3x to 1x a week, its old
# weeks read as Mon -> Mon and the new Monday median has history at once.
# Going the other way (1x -> 3x) cannot be split; the new order days build
# up their own history. The usual length per order day comes from the
# schedule (days to the next count day). A window that is longer (a missed
# count, or an older schedule) or shorter (an extra count) is still correct
# usage but is flagged and left out of the normal usage per order day =
# median regular of the last 4 usual windows (looking back before the
# selected range too, so the number does not depend on the range).
# Par Check uses real (not joined) windows only.
#
# All amounts are base quantities. Each stored amount is converted from its
# own base unit to the product's current base unit with today's conversions;
# anything that cannot be converted is left out and flagged, never guessed.
#
# ORDERED (per window) = what the store asked for on the orders delivered in
# the window (regular and extra; the store's number before any commissary
# change, returned lines included). Not part of the math: received is.
#
# PAR CHECK (/api/usage/par-check) reads the same windows from the other side:
# the par the order was made with (snapshot on the start count's order sheet),
# what the store stocked up to (start count + regular orders received), what
# it used (regular) and what was LEFT at the next count. A par that always
# leaves a lot behind is higher than the order day needs. Per order day:
# medians and the LOWEST left over of the last 4 usual windows. Windows with
# extra orders are NOT left out (caterings are too frequent to split windows
# by; stores use close to what is sent for a catering); they are marked.
#
# Endpoints in this file:
#   GET  /api/usage             get_usage
#   GET  /api/usage/par-check   get_par_check
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

LOOKBACK_DAYS = 60       # how far before date_from to look (start counts + normal usage history)
SOURCES = {'oh': 'count_sheet', 'inv': 'manual'}
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


def _read_args():
    """Shared query params. Returns (args, None) or (None, error response)."""
    try:
        date_to   = date.fromisoformat(request.args.get('date_to') or date.today().isoformat())
        date_from = date.fromisoformat(request.args.get('date_from') or (date_to - timedelta(days=28)).isoformat())
    except ValueError:
        return None, (jsonify({'error': 'Dates must be YYYY-MM-DD'}), 400)
    if date_from > date_to:
        return None, (jsonify({'error': 'From date is after To date'}), 400)
    source = request.args.get('source', 'oh')
    if source not in ('oh', 'inv', 'all'):
        return None, (jsonify({'error': 'source must be oh, inv or all'}), 400)
    return {
        'date_from':   date_from,
        'date_to':     date_to,
        'search':      (request.args.get('search') or '').strip(),
        'category_id': request.args.get('category_id', type=int),
        'source':      source,
    }, None


def _load(args):
    """
    Everything both reports need: the location, every product's windows over
    the range plus LOOKBACK_DAYS of history (usual lengths and normal usage
    need it). Returns (ctx, None) or (None, error response).
    """
    date_from, date_to, source = args['date_from'], args['date_to'], args['source']
    search, category_id = args['search'], args['category_id']

    with get_engine().connect() as conn:
        if _is_admin():
            location_id = request.args.get('location_id')
            if not location_id:
                return None, (jsonify({'error': 'Choose a location'}), 400)
        else:
            location_id = _get_user_location(conn)
            if not location_id:
                return None, (jsonify({'error': 'No location is linked to your account'}), 403)
        location_id = str(location_id)

        location = conn.execute(text("""
            SELECT store_guid::text AS location_id, location_name
            FROM locations WHERE store_guid::text = :loc
        """), {'loc': location_id}).mappings().fetchone()
        if not location:
            return None, (jsonify({'error': 'Location not found'}), 404)

        look_from = date_from - timedelta(days=LOOKBACK_DAYS)
        params = {'loc': location_id, 'look_from': look_from, 'to': date_to, 'tz': STORE_TZ}
        ctx = {'location': location, 'args': args, 'products': {}, 'histories': {}}

        # ── Products + their counts ─────────────────────────────────────────
        # Each count carries the par its order sheet was made with (order
        # sheet inventories only; NULL for a standalone inventory).
        pfilters = []
        if search:
            pfilters.append('p.name ILIKE :search')
            params['search'] = f'%{search}%'
        if category_id:
            pfilters.append('p.category_id = :category_id')
            params['category_id'] = category_id
        pwhere = ('AND ' + ' AND '.join(pfilters)) if pfilters else ''

        if source == 'all':
            counts = conn.execute(text(f"""
                SELECT ic.product_id, ic.count_date, ic.base_quantity, ic.base_unit_id,
                       ic.inventory_submission_id,
                       isc.par_qty, isc.par_unit_id, isc.par_base_qty, isc.base_unit_id AS par_base_unit_id
                FROM inventory_counts ic
                JOIN products p ON p.id = ic.product_id
                LEFT JOIN inventory_submission_counts isc
                       ON isc.inventory_submission_id = ic.inventory_submission_id
                      AND isc.product_id = ic.product_id
                WHERE ic.location_id = :loc
                  AND ic.count_date BETWEEN CAST(:look_from AS date) AND CAST(:to AS date)
                  AND ic.base_quantity IS NOT NULL
                  {pwhere}
                ORDER BY ic.product_id, ic.count_date
            """), params).mappings().all()
        else:
            # One source only: its latest submitted count per product per day
            params['src'] = SOURCES[source]
            counts = conn.execute(text(f"""
                SELECT DISTINCT ON (isc.product_id, ivs.count_date)
                       isc.product_id, ivs.count_date, isc.base_quantity, isc.base_unit_id,
                       ivs.id AS inventory_submission_id,
                       isc.par_qty, isc.par_unit_id, isc.par_base_qty, isc.base_unit_id AS par_base_unit_id
                FROM inventory_submission_counts isc
                JOIN inventory_submissions ivs ON ivs.id = isc.inventory_submission_id
                JOIN products p ON p.id = isc.product_id
                WHERE ivs.location_id = :loc
                  AND ivs.status = 'submitted'
                  AND ivs.source = :src
                  AND ivs.count_date BETWEEN CAST(:look_from AS date) AND CAST(:to AS date)
                  AND isc.base_quantity IS NOT NULL
                  {pwhere}
                ORDER BY isc.product_id, ivs.count_date,
                         ivs.submitted_at DESC NULLS LAST, ivs.id DESC
            """), params).mappings().all()

        product_ids = sorted({r['product_id'] for r in counts})
        if not product_ids:
            return ctx, None
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
        # asked = the store's number (original_quantity when the commissary
        # changed the line, else the line quantity), in the order unit.
        receipts = conn.execute(text("""
            SELECT poi.product_id, poi.base_quantity, poi.base_unit_id, poi.received_status,
                   COALESCE(poi.original_quantity, poi.order_quantity) AS asked_quantity,
                   poi.order_unit_id,
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
        ctx['pending'] = conn.execute(text("""
            SELECT po.id, po.expected_date, v.name AS vendor_name
            FROM purchase_orders po JOIN vendors v ON v.id = po.vendor_id
            WHERE po.location_id = :loc AND po.status = 'shipped'
              AND COALESCE(po.expected_date, po.order_date) <= CAST(:to AS date)
            ORDER BY po.expected_date
        """), params).mappings().all()

        # Conversions: every unit any stored amount is in -> product base units
        unit_ids = {r['base_unit_id'] for r in counts} \
                 | {r['par_unit_id'] for r in counts} \
                 | {r['par_base_unit_id'] for r in counts} \
                 | {r['base_unit_id'] for r in receipts} \
                 | {r['order_unit_id'] for r in receipts} \
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

    by_pid = {}
    for r in counts:
        by_pid.setdefault(r['product_id'], []).append(r)
    rec_by_pid, tr_by_pid = {}, {}
    for r in receipts:
        rec_by_pid.setdefault(r['product_id'], []).append(r)
    for r in transfers:
        tr_by_pid.setdefault(r['product_id'], []).append(r)

    for pid, plist in by_pid.items():
        p = products[pid]
        # The product's CURRENT count days, then every window (history
        # included) from counts on those days only. Usage adds up across
        # windows, so skipping a count joins two windows into one exact wider
        # window: after a 3x -> 1x change the old weeks read as Mon -> Mon.
        days = _count_days(plist)
        kept = [c for c in plist if days is None or _d(c['count_date']).weekday() in days]
        if days is not None and len(kept) < 2:
            days, kept = None, plist
        pos = {id(c): i for i, c in enumerate(plist)}
        history = []
        for a, b in zip(kept, kept[1:]):
            w = _window(pid, a, b, _d(a['count_date']), _d(b['count_date']),
                        rec_by_pid.get(pid, []), tr_by_pid.get(pid, []), to_base)
            w['skipped_counts'] = pos[id(b)] - pos[id(a)] - 1
            history.append(w)
        if not any(date_from <= _d(w['end_date']) <= date_to for w in history):
            continue

        # Usual window length per order day: from the current schedule (days
        # to the next count day); without a schedule, the most common length.
        if days is not None:
            usual = {WEEKDAYS[d]: _gap_to_next(d, days) for d in days}
        else:
            lengths = {}
            for w in history:
                lengths.setdefault(w['order_day'], []).append(w['days'])
            usual = {day: min(set(ls), key=lambda n: (-ls.count(n), n)) for day, ls in lengths.items()}
        for w in history:
            u = usual.get(w['order_day'], w['days'])
            w['usual'] = w['days'] == u
            if w['skipped_counts']:
                w['flags'].append({'code': 'joined',
                    'text': f"Joined: {w['skipped_counts']} count{'s' if w['skipped_counts'] != 1 else ''} in between "
                            "skipped to match the current count days. Usage is exact (the counts in between cancel out)."})
            if w['days'] > u:
                w['flags'].append({'code': 'longer_than_usual',
                    'text': f"{w['days']} days instead of the usual {u}: a count was missed, or an older, less frequent "
                            "schedule. Usage is still right; left out of the normal per order day."})
            elif w['days'] < u:
                w['flags'].append({'code': 'shorter_than_usual',
                    'text': f"{w['days']} days instead of the usual {u}: an extra count. "
                            "Usage is still right; left out of the normal per order day."})
        ctx.setdefault('count_days', {})[pid] = days

        disp_f = base_factor(conv_map, p['display_unit_id'], p['base_unit_id'], pid)
        ctx['products'][pid] = {
            'product_id':      pid,
            'product_name':    p['name'],
            'category_id':     p['category_id'],
            'category':        p['category'],
            'base_unit':       unit_names.get(p['base_unit_id']),
            'display_unit':    unit_names.get(p['display_unit_id']) if disp_f else unit_names.get(p['base_unit_id']),
            'display_factor':  disp_f or 1.0,          # 1 display unit = this many base units
            # current count days (Mon first); None = no steady schedule found
            'count_days':      [WEEKDAYS[d] for d in sorted(days)] if days is not None else None,
        }
        ctx['histories'][pid] = (history, usual)
    return ctx, None


SCHEDULE_WEEKS = 3      # current count days: weekdays counted in at least 2 of the last 3 weeks


def _count_days(plist):
    """
    A product's current count days (set of weekday numbers, Monday = 0): the
    weekdays it was counted on in at least 2 of the last 3 weeks (weeks counted
    back from its latest count). One missed or one extra count does not change
    the schedule; a real change shows after a week. With less history: at
    least half the weeks there are. None when nothing qualifies.
    """
    if not plist:
        return None
    last = _d(plist[-1]['count_date'])
    seen = {}
    weeks = set()
    for c in plist:
        age = (last - _d(c['count_date'])).days // 7
        if age < SCHEDULE_WEEKS:
            weeks.add(age)
            seen.setdefault(_d(c['count_date']).weekday(), set()).add(age)
    n = len(weeks)
    need = 2 if n >= SCHEDULE_WEEKS else max(1, (n + 1) // 2)
    days = {d for d, ws in seen.items() if len(ws) >= need}
    return days or None


def _gap_to_next(day, days):
    """Days from count day `day` to the next count day (7 when it is the only one)."""
    for k in range(1, 8):
        if (day + k) % 7 in days:
            return k
    return 7


def _covers(day, n_days):
    """Monday order covering 2 days -> 'Tue–Wed'"""
    first = WEEKDAYS[(WEEKDAYS.index(day) + 1) % 7]
    last  = WEEKDAYS[(WEEKDAYS.index(day) + n_days) % 7]
    return first[:3] if n_days == 1 else f'{first[:3]}–{last[:3]}'


def _last_usual(history, date_to, keep=None, n=4):
    """Per order day: the last n usual windows ending by date_to (newest first) that pass keep()."""
    picked = {}
    for w in sorted(history, key=lambda x: x['start_date'], reverse=True):
        if not w['usual'] or _d(w['end_date']) > date_to or (keep and not keep(w)):
            continue
        lst = picked.setdefault(w['order_day'], [])
        if len(lst) < n:
            lst.append(w)
    return picked


def _base_response(ctx):
    a = ctx['args']
    loc = ctx['location']
    return {
        'location_id':    loc['location_id'],
        'location_name':  loc['location_name'],
        'date_from':      a['date_from'].isoformat(),
        'date_to':        a['date_to'].isoformat(),
        'timezone':       STORE_TZ,
        'source':         a['source'],
        'pending_orders': [{'id': r['id'], 'vendor_name': r['vendor_name'],
                            'expected_date': str(r['expected_date'])[:10] if r['expected_date'] else None}
                           for r in ctx.get('pending', [])],
        'products':       [],
    }


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
        source        oh (order sheets, default) | inv (inventories) | all
    """
    args, err = _read_args()
    if err:
        return err
    ctx, err = _load(args)
    if err:
        return err
    date_from, date_to = args['date_from'], args['date_to']

    out = []
    for pid, (history, usual) in ctx['histories'].items():
        # Normal usage per order day: median regular of the last 4 usual windows
        normal_out = []
        picked = _last_usual(history, date_to, keep=lambda w: w['regular'] is not None)
        for day, ws in sorted(picked.items(), key=lambda kv: WEEKDAYS.index(kv[0])):
            normal_out.append({
                'order_day':      day,
                'covers':         _covers(day, usual[day]),
                'days':           usual[day],
                'median_regular': round(median(w['regular'] for w in ws), 4),
                'windows':        len(ws),
            })

        windows = [w for w in history if date_from <= _d(w['end_date']) <= date_to]
        tot = lambda k: round(sum(w[k] for w in windows if w[k] is not None), 4)
        out.append({
            **ctx['products'][pid],
            'totals': {
                'ordered': tot('ordered'),
                'actual':  tot('actual'),
                'extra':   tot('extra'),
                'regular': tot('regular'),
            },
            'normal_by_order_day': normal_out,
            # Things to check (an unusual window length is not one: its usage is still right)
            'flag_count':      sum(1 for w in windows for f in w['flags']
                                   if f['code'] not in ('longer_than_usual', 'shorter_than_usual', 'joined')),
            'windows':         sorted(windows, key=lambda x: x['end_date'], reverse=True),
        })

    out.sort(key=lambda x: ((x['category'] or '~'), x['product_name']))
    resp = _base_response(ctx)
    resp['products'] = out
    return jsonify(resp)


@bp.route('/usage/par-check', methods=['GET'])
@manage_required
def get_par_check():
    """
    Same query params as /usage. Per product and order day (last 4 usual
    windows ending by date_to; windows with extra orders included, marked):
        par              the par on the latest of those windows' order sheets
        stocked_to       median of start count + regular orders received
        used             median regular usage
        left             median left at the next count
        lowest_left      the least that was left (how close it came to running out)
        ran_out          windows that ended at 0
    plus every window in the range with the same numbers.
    """
    args, err = _read_args()
    if err:
        return err
    ctx, err = _load(args)
    if err:
        return err
    date_from, date_to = args['date_from'], args['date_to']

    def med(vals):
        vals = [v for v in vals if v is not None]
        return round(median(vals), 4) if vals else None

    out = []
    for pid, (history, usual) in ctx['histories'].items():
        picked = _last_usual(history, date_to,
                             keep=lambda w: not w['skipped_counts'] and w['end'] is not None and w['start'] is not None)
        days_out = []
        for day, ws in sorted(picked.items(), key=lambda kv: WEEKDAYS.index(kv[0])):
            lefts = [w['end'] for w in ws]
            days_out.append({
                'order_day':   day,
                'covers':      _covers(day, usual[day]),
                'days':        usual[day],
                'par':         next((w['par'] for w in ws if w['par'] is not None), None),
                'stocked_to':  med(w['stocked_to'] for w in ws),
                'used':        med(w['regular'] for w in ws),
                'left':        med(lefts),
                'lowest_left': round(min(lefts), 4),
                'ran_out':     sum(1 for v in lefts if v <= 0),
                'with_extra':  sum(1 for w in ws if w['extra']),
                'windows':     len(ws),
            })

        # Joined windows (an older, more frequent schedule) span several
        # deliveries: their par / stocked to / left over say nothing about
        # the current par, so Par Check lists real windows only.
        windows = [w for w in history if date_from <= _d(w['end_date']) <= date_to and not w['skipped_counts']]
        out.append({
            **ctx['products'][pid],
            'joined_hidden': sum(1 for w in history if date_from <= _d(w['end_date']) <= date_to and w['skipped_counts']),
            'by_order_day': days_out,
            'windows': [{
                'start_date':  w['start_date'],
                'end_date':    w['end_date'],
                'covers_from': w['covers_from'],
                'order_day':   w['order_day'],
                'usual':       w['usual'],
                'days':        w['days'],
                'par':         w['par'],
                'start':       w['start'],
                'received_regular': w['received_regular'],
                'stocked_to':  w['stocked_to'],
                'used':        w['regular'],
                'left':        w['end'],
                'extra':       w['extra'],
                'start_inventory_id': w['start_inventory_id'],
                'end_inventory_id':   w['end_inventory_id'],
            } for w in sorted(windows, key=lambda x: x['end_date'], reverse=True)],
        })

    out.sort(key=lambda x: ((x['category'] or '~'), x['product_name']))
    resp = _base_response(ctx)
    resp['products'] = out
    return jsonify(resp)


def _window(pid, a, b, start_day, end_day, receipts, transfers, to_base):
    """One product, one count-to-count window."""
    flags, sources = [], []

    def inside(day):
        return day is not None and start_day < day <= end_day

    start = to_base(a['base_quantity'], a['base_unit_id'], pid)
    end   = to_base(b['base_quantity'], b['base_unit_id'], pid)
    if start is None or end is None:
        flags.append({'code': 'count_unconverted',
                      'text': "A count is in a unit that no longer converts to the product's base unit"})

    received = received_regular = extra = t_in = t_out = ordered = 0.0
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
            if not is_extra:
                received_regular += qty
            asked = to_base(r['asked_quantity'], r['order_unit_id'], pid)
            ordered += asked if asked is not None else qty
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

    # The par this window's order was made with (start count's order sheet).
    # Converted from par_qty + par unit with today's conversions; else the
    # stored base snapshot.
    par = to_base(a.get('par_qty'), a.get('par_unit_id'), pid)
    if par is None:
        par = to_base(a.get('par_base_qty'), a.get('par_base_unit_id'), pid)

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


    return {
        'start_date':    start_day.isoformat(),
        'end_date':      end_day.isoformat(),
        'covers_from':   (start_day + timedelta(days=1)).isoformat(),   # counts are end of day
        'order_day':     WEEKDAYS[start_day.weekday()],
        'days':          (end_day - start_day).days,
        'start':         round(start, 4) if start is not None else None,
        'start_inventory_id': a['inventory_submission_id'],
        'ordered':       round(ordered, 4),
        'received':      round(received, 4),
        'received_regular': round(received_regular, 4),
        'par':           round(par, 4) if par is not None else None,
        'stocked_to':    round(start + received_regular, 4) if start is not None else None,
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
