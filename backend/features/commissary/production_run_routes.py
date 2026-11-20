# =============================================================================
# backend/features/commissary/production_run_routes.py
# =============================================================================
# Production (commissary): what the commissary made.
#
# A PRODUCTION RUN is one filled-in production template for one commissary and
# one production date: draft -> submitted. Several runs a day add up; the day's
# production of a product is the sum of that day's SUBMITTED runs.
#
# Amounts follow the base-unit principle: each line stores the amount as
# entered (quantity + unit) AND converted at save (base_quantity + base unit).
# The unit comes from the template on the server, never from the browser. A
# line keeps the unit it was first entered in, even if the template changes.
#
# Who:
#   record (create, save, submit drafts)   admin, commissary GM, commissary staff
#                                          (staff: their own commissary only)
#   correct / delete a SUBMITTED run       PRODUCTION_EDIT_ROLES (core/auth.py)
#   Corrections keep the first submitted value in original_quantity, with
#   who / when / why.
#
# Endpoints in this file:
#   GET     /api/commissary-locations                    list_commissaries
#   GET     /api/production-runs                         list_production_runs
#   POST    /api/production-runs                         create_production_run
#   GET     /api/production-runs/<int:run_id>            get_production_run
#   PUT     /api/production-runs/<int:run_id>/save       save_production_run
#   POST    /api/production-runs/<int:run_id>/submit     submit_production_run
#   DELETE  /api/production-runs/<int:run_id>            delete_production_run
#   GET     /api/production-daily                        production_daily
# =============================================================================

from datetime import datetime
import os
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
import logging

from core.auth import comm_required, can_edit_submitted_production, _is_admin, _get_user_location
from core.database import get_engine
from core.units import load_base_units, load_conversion_map, base_factor
from features.commissary.commissary_access import (
    CommissaryAccessError, list_commissary_locations, resolve_commissary_location,
)
from features.commissary.production_template_routes import load_production_template

logger = logging.getLogger(__name__)

bp = Blueprint('production_run_routes', __name__, url_prefix='/api')

STORE_TZ = os.environ.get('STORE_TIMEZONE', 'America/New_York')


def _today_local():
    return datetime.now(ZoneInfo(STORE_TZ)).date().isoformat()


def _num(v):
    return None if v is None else float(v)


def _access_response(e):
    return jsonify({'error': str(e)}), e.status


def _load_run(conn, run_id):
    """Run header, checked against the user's commissary. Raises CommissaryAccessError."""
    run = conn.execute(text("""
        SELECT pr.id, pr.template_id, pr.location_id, pr.production_date, pr.status,
               pr.notes, pr.created_by, pr.created_at, pr.updated_at,
               pr.submitted_by, pr.submitted_at,
               pt.name AS template_name, l.location_name
        FROM production_runs pr
        LEFT JOIN production_templates pt ON pt.id = pr.template_id
        LEFT JOIN locations l             ON l.store_guid::text = pr.location_id
        WHERE pr.id = :id
    """), {'id': run_id}).mappings().fetchone()
    if not run:
        raise CommissaryAccessError('Production run not found', 404)
    if not _is_admin():
        own = _get_user_location(conn)
        if not own or str(own) != str(run['location_id']):
            raise CommissaryAccessError('You do not have access to this production run', 403)
    return dict(run)


def _can_edit(run):
    return run['status'] == 'draft' or can_edit_submitted_production()


# =============================================================================
# Commissaries
# =============================================================================

@bp.route('/commissary-locations', methods=['GET'])
@comm_required
def list_commissaries():
    """Admins: every commissary. Everyone else: their own, when it is a commissary."""
    with get_engine().connect() as conn:
        all_comm = list_commissary_locations(conn)
        if _is_admin():
            return jsonify(all_comm)
        own = _get_user_location(conn)
    return jsonify([c for c in all_comm if own and c['store_guid'] == str(own)])


# =============================================================================
# Runs: list / create
# =============================================================================

@bp.route('/production-runs', methods=['GET'])
@comm_required
def list_production_runs():
    """
    Filters: location_id (admins; staff always see their own), date_from,
    date_to, status, template_id. Paged: page, per_page. Newest first.
    """
    page     = max(1, request.args.get('page', 1, type=int))
    per_page = min(100, max(1, request.args.get('per_page', 25, type=int)))
    try:
        with get_engine().connect() as conn:
            location_id = resolve_commissary_location(
                conn, request.args.get('location_id'), required=False)
            where, params = ['TRUE'], {'limit': per_page, 'offset': (page - 1) * per_page}
            if location_id:
                where.append('pr.location_id = :location_id')
                params['location_id'] = location_id
            if request.args.get('date_from'):
                where.append('pr.production_date >= CAST(:date_from AS date)')
                params['date_from'] = request.args['date_from']
            if request.args.get('date_to'):
                where.append('pr.production_date <= CAST(:date_to AS date)')
                params['date_to'] = request.args['date_to']
            if request.args.get('status') in ('draft', 'submitted'):
                where.append('pr.status = :status')
                params['status'] = request.args['status']
            if request.args.get('template_id'):
                where.append('pr.template_id = :template_id')
                params['template_id'] = request.args.get('template_id', type=int)
            where_sql = ' AND '.join(where)

            total = conn.execute(text(f"""
                SELECT COUNT(*) AS n FROM production_runs pr WHERE {where_sql}
            """), params).fetchone().n
            rows = conn.execute(text(f"""
                SELECT pr.id, pr.template_id, pt.name AS template_name,
                       pr.location_id, l.location_name,
                       pr.production_date, pr.status, pr.notes,
                       pr.created_by, pr.created_at, pr.submitted_by, pr.submitted_at,
                       (SELECT COUNT(*) FROM production_run_items pri
                        WHERE pri.run_id = pr.id AND pri.quantity <> 0) AS item_count,
                       (SELECT COUNT(*) FROM production_run_items pri
                        WHERE pri.run_id = pr.id AND pri.corrected_at IS NOT NULL) AS corrected_count
                FROM production_runs pr
                LEFT JOIN production_templates pt ON pt.id = pr.template_id
                LEFT JOIN locations l             ON l.store_guid::text = pr.location_id
                WHERE {where_sql}
                ORDER BY pr.production_date DESC, pr.created_at DESC, pr.id DESC
                LIMIT :limit OFFSET :offset
            """), params).mappings().all()
        return jsonify({
            'runs':     [dict(r) for r in rows],
            'total':    total,
            'page':     page,
            'per_page': per_page,
            'pages':    max(1, (total + per_page - 1) // per_page),
        })
    except CommissaryAccessError as e:
        return _access_response(e)


@bp.route('/production-runs', methods=['POST'])
@comm_required
def create_production_run():
    """
    Start a run. Staff: their own commissary. Admins: pass location_id.
    The template must be active and assigned to that commissary.
    production_date defaults to today (STORE_TIMEZONE).
    """
    data        = request.get_json(force=True) or {}
    template_id = data.get('template_id')
    prod_date   = data.get('production_date') or _today_local()
    if not template_id:
        return jsonify({'error': 'template_id is required'}), 400
    try:
        with get_engine().begin() as conn:
            location_id = resolve_commissary_location(conn, data.get('location_id'))
            assigned = conn.execute(text("""
                SELECT 1
                FROM production_templates pt
                JOIN production_template_locations ptl ON ptl.template_id = pt.id
                WHERE pt.id = :tid AND pt.active = TRUE AND ptl.location_id = :lid
            """), {'tid': template_id, 'lid': location_id}).fetchone()
            if not assigned:
                return jsonify({'error': 'That production template is not assigned to this commissary'}), 400
            row = conn.execute(text("""
                INSERT INTO production_runs (template_id, location_id, production_date,
                                             status, notes, created_by)
                VALUES (:tid, :lid, CAST(:d AS date), 'draft', :notes, :by)
                RETURNING id
            """), {'tid': template_id, 'lid': location_id, 'd': prod_date,
                   'notes': data.get('notes'), 'by': g.user.get('email')}).fetchone()
        return jsonify({'id': row.id}), 201
    except CommissaryAccessError as e:
        return _access_response(e)


# =============================================================================
# Run: get
# =============================================================================

def _run_lines(conn, run_id):
    rows = conn.execute(text("""
        SELECT pri.id, pri.product_id, p.name AS product_name,
               pri.quantity, pri.unit_id, u.name AS unit_name,
               pri.base_quantity, pri.base_unit_id, bu.name AS base_unit,
               pri.entered_by, pri.entered_at,
               pri.original_quantity, pri.corrected_by, pri.corrected_at, pri.correction_notes
        FROM production_run_items pri
        JOIN products p ON p.id = pri.product_id
        LEFT JOIN units u  ON u.id  = pri.unit_id
        LEFT JOIN units bu ON bu.id = pri.base_unit_id
        WHERE pri.run_id = :id
        ORDER BY p.name
    """), {'id': run_id}).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ('quantity', 'base_quantity', 'original_quantity'):
            d[k] = _num(d[k])
        out.append(d)
    return out


@bp.route('/production-runs/<int:run_id>', methods=['GET'])
@comm_required
def get_production_run(run_id):
    """
    The run, laid out on its template's sections. Each item carries the unit
    to enter in (the line's own unit once entered, else the template's), the
    line if there is one, and `earlier_today`: what OTHER submitted runs at
    this commissary made of that product on the same date (in this item's
    unit when it converts, plus base).
    Products on the run that the template no longer has go in an extra
    section "Other products".
    """
    try:
        with get_engine().connect() as conn:
            run = _load_run(conn, run_id)
            lines = _run_lines(conn, run_id)
            by_product = {l['product_id']: l for l in lines}

            template = load_production_template(conn, run['template_id']) if run['template_id'] else None
            sections = []
            on_template = set()
            for s in (template or {}).get('sections', []):
                items = []
                for it in s['items']:
                    if it['product_id'] in on_template:
                        continue            # same product twice on one template: show it once
                    on_template.add(it['product_id'])
                    line = by_product.get(it['product_id'])
                    items.append({
                        'product_id':   it['product_id'],
                        'product_name': it['product_name'],
                        'category':     it['category'],
                        'unit_id':      line['unit_id'] if line else it['unit_id'],
                        'unit_name':    line['unit_name'] if line else it['unit_name'],
                        'base_unit_id': it['base_unit_id'],
                        'base_unit':    it['base_unit'],
                        'line':         line,
                    })
                sections.append({'id': s['id'], 'name': s['name'], 'items': items})
            extra = [l for l in lines if l['product_id'] not in on_template]
            if extra:
                sections.append({'id': 'other', 'name': 'Other products', 'items': [{
                    'product_id':   l['product_id'],
                    'product_name': l['product_name'],
                    'category':     None,
                    'unit_id':      l['unit_id'],
                    'unit_name':    l['unit_name'],
                    'base_unit_id': l['base_unit_id'],
                    'base_unit':    l['base_unit'],
                    'line':         l,
                    'not_on_template': True,
                } for l in extra]})

            # What other submitted runs made today, per product (base units).
            others = conn.execute(text("""
                SELECT pri.product_id, pri.base_unit_id, bu.name AS base_unit,
                       SUM(pri.base_quantity) AS base_total, COUNT(DISTINCT pr.id) AS runs
                FROM production_runs pr
                JOIN production_run_items pri ON pri.run_id = pr.id
                LEFT JOIN units bu ON bu.id = pri.base_unit_id
                WHERE pr.location_id = :lid AND pr.production_date = :d
                  AND pr.status = 'submitted' AND pr.id <> :id
                GROUP BY pri.product_id, pri.base_unit_id, bu.name
            """), {'lid': run['location_id'], 'd': run['production_date'], 'id': run_id}).fetchall()

            all_items = [it for s in sections for it in s['items']]
            pids  = {it['product_id'] for it in all_items}
            units = {it['unit_id'] for it in all_items}
            bases = {r.base_unit_id for r in others}
            conv  = load_conversion_map(conn, pids, units, bases) if others else {}
            earlier = {}
            for r in others:
                earlier.setdefault(r.product_id, []).append(r)
            for it in all_items:
                rows = earlier.get(it['product_id'])
                if not rows:
                    it['earlier_today'] = None
                    continue
                total_in_unit, ok = 0.0, True
                for r in rows:
                    f = base_factor(conv, it['unit_id'], r.base_unit_id, it['product_id'])
                    if not f:
                        ok = False
                        break
                    total_in_unit += float(r.base_total) / f
                it['earlier_today'] = {
                    'runs':      sum(r.runs for r in rows),
                    'quantity':  round(total_in_unit, 4) if ok else None,
                    'unit_name': it['unit_name'],
                    'base':      [{'quantity': float(r.base_total), 'unit_name': r.base_unit}
                                  for r in rows],
                }

        run['sections']   = sections
        run['lines']      = lines
        run['can_edit']   = _can_edit(run)
        run['can_delete'] = run['status'] == 'draft' or can_edit_submitted_production()
        return jsonify(run)
    except CommissaryAccessError as e:
        return _access_response(e)


# =============================================================================
# Run: save / submit / delete
# =============================================================================

@bp.route('/production-runs/<int:run_id>/save', methods=['PUT'])
@comm_required
def save_production_run(run_id):
    """
    Body: {entries: [{product_id, quantity}], correction_notes?}
    One entry per box on the sheet. quantity null / '' = blank:
      draft      -> the line is removed
      submitted  -> treated as 0 (a correction; the earlier value is kept)
    The unit is decided here: the line's own unit if it exists, else the
    product's unit on the run's template. A product that is neither on the run
    nor on the template is refused.
    Every unit must convert to the product's base unit, or nothing is saved
    (missing_conversions lists what is missing).
    """
    data    = request.get_json(force=True) or {}
    entries = data.get('entries') or []
    notes   = (data.get('correction_notes') or '').strip() or None
    user    = g.user.get('email')

    parsed = {}
    for e in entries:
        try:
            pid = int(e.get('product_id'))
        except (TypeError, ValueError):
            return jsonify({'error': 'Every entry needs a product_id'}), 400
        q = e.get('quantity')
        if q is None or (isinstance(q, str) and not q.strip()):
            parsed[pid] = None
            continue
        try:
            q = float(q)
        except (TypeError, ValueError):
            return jsonify({'error': f'Not a number: {q}'}), 400
        if q < 0:
            return jsonify({'error': 'Amounts cannot be negative'}), 400
        parsed[pid] = q

    try:
        with get_engine().begin() as conn:
            run = _load_run(conn, run_id)
            if not _can_edit(run):
                return jsonify({'error': 'This production run was submitted. Only an admin or '
                                         'commissary GM can change it.'}), 403
            submitted = run['status'] == 'submitted'

            existing = {r.product_id: r for r in conn.execute(text("""
                SELECT product_id, quantity, unit_id, base_quantity, original_quantity
                FROM production_run_items WHERE run_id = :id
            """), {'id': run_id}).fetchall()}
            template_units = {r.product_id: r.unit_id for r in conn.execute(text("""
                SELECT DISTINCT ON (pti.product_id) pti.product_id, pti.unit_id
                FROM production_template_items pti
                JOIN production_template_sections pts ON pts.id = pti.section_id
                WHERE pts.template_id = :tid
                ORDER BY pti.product_id, pts.sort_order, pti.sort_order, pti.id
            """), {'tid': run['template_id']}).fetchall()} if run['template_id'] else {}

            unit_for = {}
            for pid in parsed:
                if pid in existing:
                    unit_for[pid] = existing[pid].unit_id
                elif pid in template_units:
                    unit_for[pid] = template_units[pid]
                elif parsed[pid] is not None:
                    return jsonify({'error': f'Product {pid} is not on this production template'}), 400

            pids  = set(unit_for)
            bases = load_base_units(conn, pids)
            conv  = load_conversion_map(conn, pids, set(unit_for.values()), set(bases.values()))

            missing, writes, removes = [], [], []
            for pid, qty in parsed.items():
                if pid not in unit_for:
                    continue                      # blank box for a product with no line: nothing to do
                old = existing.get(pid)
                if qty is None:
                    if not old:
                        continue
                    if not submitted:
                        removes.append(pid)
                        continue
                    qty = 0.0
                if old and float(old.quantity) == qty:
                    continue                      # unchanged
                base_unit = bases.get(pid)
                f = base_factor(conv, unit_for[pid], base_unit, pid)
                if f is None:
                    missing.append({'product_id': pid, 'unit_id': unit_for[pid]})
                    continue
                writes.append({'pid': pid, 'qty': qty, 'uid': unit_for[pid],
                               'bq': round(qty * f, 4), 'bu': base_unit,
                               'old_qty': float(old.quantity) if old else None})

            if missing:
                names = conn.execute(text("""
                    SELECT m.pid AS product_id, m.uid AS unit_id, p.name AS product_name,
                           u.name AS unit_name, bu.name AS base_unit
                    FROM unnest(CAST(:pids AS bigint[]), CAST(:uids AS integer[])) AS m(pid, uid)
                    JOIN products p ON p.id = m.pid
                    LEFT JOIN units u  ON u.id  = m.uid
                    LEFT JOIN units bu ON bu.id = p.base_unit_id
                """), {'pids': [m['product_id'] for m in missing],
                       'uids': [m['unit_id'] for m in missing]}).mappings().all()
                raise _MissingConversions([dict(n) for n in names])

            if removes:
                conn.execute(text("""
                    DELETE FROM production_run_items WHERE run_id = :id AND product_id = ANY(:pids)
                """), {'id': run_id, 'pids': removes})
            for w in writes:
                if submitted:
                    # Correction: keep the first submitted value (0 when the line is new).
                    conn.execute(text("""
                        INSERT INTO production_run_items (
                            run_id, product_id, quantity, unit_id, base_quantity, base_unit_id,
                            entered_by, original_quantity, corrected_by, corrected_at, correction_notes
                        ) VALUES (:id, :pid, :qty, :uid, :bq, :bu, :user, 0, :user, NOW(), :notes)
                        ON CONFLICT (run_id, product_id) DO UPDATE SET
                            original_quantity = COALESCE(production_run_items.original_quantity,
                                                         production_run_items.quantity),
                            quantity          = EXCLUDED.quantity,
                            base_quantity     = EXCLUDED.base_quantity,
                            base_unit_id      = EXCLUDED.base_unit_id,
                            corrected_by      = EXCLUDED.corrected_by,
                            corrected_at      = EXCLUDED.corrected_at,
                            correction_notes  = COALESCE(EXCLUDED.correction_notes,
                                                         production_run_items.correction_notes)
                    """), dict(w, id=run_id, user=user, notes=notes))
                else:
                    conn.execute(text("""
                        INSERT INTO production_run_items (
                            run_id, product_id, quantity, unit_id, base_quantity, base_unit_id, entered_by
                        ) VALUES (:id, :pid, :qty, :uid, :bq, :bu, :user)
                        ON CONFLICT (run_id, product_id) DO UPDATE SET
                            quantity      = EXCLUDED.quantity,
                            base_quantity = EXCLUDED.base_quantity,
                            base_unit_id  = EXCLUDED.base_unit_id,
                            entered_by    = EXCLUDED.entered_by,
                            entered_at    = NOW()
                    """), dict(w, id=run_id, user=user))
            conn.execute(text("""
                UPDATE production_runs SET updated_at = NOW() WHERE id = :id
            """), {'id': run_id})
        return jsonify({'status': 'ok', 'changed': len(writes) + len(removes)})
    except CommissaryAccessError as e:
        return _access_response(e)
    except _MissingConversions as e:
        return jsonify({'error': 'Some units have no conversion to the product\'s base unit. '
                                 'Nothing was saved.',
                        'missing_conversions': e.missing}), 400


class _MissingConversions(Exception):
    def __init__(self, missing):
        super().__init__('missing conversions')
        self.missing = missing


@bp.route('/production-runs/<int:run_id>/submit', methods=['POST'])
@comm_required
def submit_production_run(run_id):
    """Submit a draft. It needs at least one amount above 0."""
    try:
        with get_engine().begin() as conn:
            run = _load_run(conn, run_id)
            if run['status'] != 'draft':
                return jsonify({'error': 'This production run was already submitted'}), 400
            n = conn.execute(text("""
                SELECT COUNT(*) AS n FROM production_run_items WHERE run_id = :id AND quantity > 0
            """), {'id': run_id}).fetchone().n
            if not n:
                return jsonify({'error': 'Enter at least one amount before submitting'}), 400
            conn.execute(text("""
                UPDATE production_runs
                SET status = 'submitted', submitted_by = :by, submitted_at = NOW(), updated_at = NOW()
                WHERE id = :id AND status = 'draft'
            """), {'id': run_id, 'by': g.user.get('email')})
        return jsonify({'status': 'ok'})
    except CommissaryAccessError as e:
        return _access_response(e)


@bp.route('/production-runs/<int:run_id>', methods=['DELETE'])
@comm_required
def delete_production_run(run_id):
    """Drafts: anyone at that commissary. Submitted: PRODUCTION_EDIT_ROLES only."""
    try:
        with get_engine().begin() as conn:
            run = _load_run(conn, run_id)
            if run['status'] == 'submitted' and not can_edit_submitted_production():
                return jsonify({'error': 'Only an admin or commissary GM can delete a submitted '
                                         'production run'}), 403
            conn.execute(text("DELETE FROM production_runs WHERE id = :id"), {'id': run_id})
        return jsonify({'status': 'ok'})
    except CommissaryAccessError as e:
        return _access_response(e)


# =============================================================================
# Day totals
# =============================================================================

@bp.route('/production-daily', methods=['GET'])
@comm_required
def production_daily():
    """
    What a commissary made, per date and product: the sum of SUBMITTED runs.
    Params: location_id (admins; required), date_from, date_to (default: today).
    Each product row: base total (+ base unit), and the total in the unit it
    was entered in when every run used the same unit. Drafts are counted per
    date (not in the totals) so the page can warn about unsubmitted runs.
    """
    date_from = request.args.get('date_from') or request.args.get('date') or _today_local()
    date_to   = request.args.get('date_to') or date_from
    try:
        with get_engine().connect() as conn:
            location_id = resolve_commissary_location(conn, request.args.get('location_id'))
            rows = conn.execute(text("""
                SELECT pr.production_date, pri.product_id, p.name AS product_name,
                       c.name AS category,
                       pri.base_unit_id, bu.name AS base_unit,
                       SUM(pri.base_quantity) AS base_total,
                       COUNT(DISTINCT pr.id)  AS runs,
                       COUNT(DISTINCT pri.unit_id) AS unit_count,
                       MIN(pri.unit_id) AS unit_id,
                       SUM(pri.quantity) AS quantity_total,
                       BOOL_OR(pri.corrected_at IS NOT NULL) AS corrected
                FROM production_runs pr
                JOIN production_run_items pri ON pri.run_id = pr.id
                JOIN products p ON p.id = pri.product_id
                LEFT JOIN product_categories c ON c.id = p.category_id
                LEFT JOIN units bu ON bu.id = pri.base_unit_id
                WHERE pr.location_id = :lid AND pr.status = 'submitted'
                  AND pr.production_date BETWEEN CAST(:df AS date) AND CAST(:dt AS date)
                GROUP BY pr.production_date, pri.product_id, p.name, c.name,
                         pri.base_unit_id, bu.name
                HAVING SUM(pri.base_quantity) <> 0
                ORDER BY pr.production_date DESC, c.name NULLS LAST, p.name
            """), {'lid': location_id, 'df': date_from, 'dt': date_to}).mappings().all()
            unit_names = {r.id: r.name for r in conn.execute(text("""
                SELECT id, name FROM units WHERE id = ANY(:ids)
            """), {'ids': list({r['unit_id'] for r in rows}) or [0]}).fetchall()}
            run_counts = conn.execute(text("""
                SELECT production_date,
                       COUNT(*) FILTER (WHERE status = 'submitted') AS submitted,
                       COUNT(*) FILTER (WHERE status = 'draft')     AS drafts
                FROM production_runs
                WHERE location_id = :lid
                  AND production_date BETWEEN CAST(:df AS date) AND CAST(:dt AS date)
                GROUP BY production_date
            """), {'lid': location_id, 'df': date_from, 'dt': date_to}).mappings().all()

        days = {}
        for rc in run_counts:
            days[str(rc['production_date'])] = {
                'date': str(rc['production_date']), 'submitted_runs': rc['submitted'],
                'draft_runs': rc['drafts'], 'products': []}
        for r in rows:
            d = days.setdefault(str(r['production_date']), {
                'date': str(r['production_date']), 'submitted_runs': 0, 'draft_runs': 0,
                'products': []})
            one_unit = r['unit_count'] == 1
            d['products'].append({
                'product_id':   r['product_id'],
                'product_name': r['product_name'],
                'category':     r['category'],
                'quantity':     _num(r['quantity_total']) if one_unit else None,
                'unit_name':    unit_names.get(r['unit_id']) if one_unit else None,
                'base_quantity': _num(r['base_total']),
                'base_unit':    r['base_unit'],
                'runs':         r['runs'],
                'corrected':    bool(r['corrected']),
            })
        return jsonify({
            'location_id': location_id,
            'date_from':   date_from,
            'date_to':     date_to,
            'days':        sorted(days.values(), key=lambda d: d['date'], reverse=True),
        })
    except CommissaryAccessError as e:
        return _access_response(e)
