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
# END INVENTORY: each product also has an End Inv box (what is on hand after
# production, like the paper sheet). The End Inv boxes of a run ARE an ordinary
# commissary inventory (inventory_submissions, source 'production', dated the
# production date), created on the first End Inv saved and linked from
# production_runs.inventory_submission_id. Its lines are written with the
# inventory service, so every inventory rule applies: drafts do not count,
# submitting the run submits the inventory, the latest submitted count of the
# day wins product by product, corrections keep a trail. Blank End Inv = not
# counted. End Inv is entered in the same unit as Made.
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
#
# QC WEIGHTS: products an admin set up for QC (product_qc_specs) get up to
# QC_SAMPLES weight boxes per run; see production_qc.py. A check keeps the spec in
# force when its weights were first saved. Changing weights on a submitted run is
# a correction (signed), like Made and End Inv.
#
# STORAGE AREAS (storage_areas_plan.md): a run is FOR an area of the commissary
# (storage_area_id, NULL = Main), chosen when it starts, default Main. Made goes into
# that area and the run's End Inv is THAT area's count (its inventory carries the
# area). "Earlier today" only counts runs of the same area. Lists / day totals can
# be filtered by area (?storage_area_id=).
#
# MADE BY: each product row can carry a name, TYPED by whoever fills in the sheet
# (like the names next to each product on the paper sheet): who made it, and so
# who weighed its QC bags. No PIN, no Toast link (production_run_made_by).
#
# Signing (core/operators.py): submitting a run and correcting a submitted run
# are signed by the person signed in on the device (or the personal login).
# On a shared login with nobody signed in they answer 428 operator_required.
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
from features.inventory.inventory_count_service import (
    supersede_line_pairs, insert_lines, sync_counts_from_entries,
    refresh_day_counts, adopt_day_counts,
)
from features.commissary.commissary_access import (
    CommissaryAccessError, list_commissary_locations, resolve_commissary_location,
)
from features.commissary.production_template_routes import load_production_template
from core.operators import signer_for, record_signoff, OperatorRequired, operator_required_response
from features.commissary.production_qc import load_specs, load_checks, evaluate, QC_SAMPLES
from features.commissary.storage_areas import resolve_area, AreaError

# A run's area (NULL storage_area_id = the location's Main area), for SQL on `pr`.
AREA_EXPR = ("COALESCE(pr.storage_area_id, (SELECT m.id FROM storage_areas m "
             "WHERE m.location_id = pr.location_id AND m.kind = 'main'))")

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
               pr.submitted_by, pr.submitted_at, pr.inventory_submission_id,
               pt.name AS template_name, l.location_name,
               COALESCE(pr.storage_area_id, ma.id) AS storage_area_id,
               COALESCE(sa.name, ma.name)          AS storage_area_name
        FROM production_runs pr
        LEFT JOIN production_templates pt ON pt.id = pr.template_id
        LEFT JOIN locations l             ON l.store_guid::text = pr.location_id
        LEFT JOIN storage_areas sa        ON sa.id = pr.storage_area_id
        LEFT JOIN storage_areas ma        ON ma.location_id = pr.location_id AND ma.kind = 'main'
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
            if request.args.get('storage_area_id'):
                where.append(f'{AREA_EXPR} = :area_id')
                params['area_id'] = request.args.get('storage_area_id', type=int)
            where_sql = ' AND '.join(where)

            total = conn.execute(text(f"""
                SELECT COUNT(*) AS n FROM production_runs pr WHERE {where_sql}
            """), params).fetchone().n
            rows = conn.execute(text(f"""
                SELECT pr.id, pr.template_id, pt.name AS template_name,
                       pr.location_id, l.location_name,
                       {AREA_EXPR} AS storage_area_id,
                       (SELECT a.name FROM storage_areas a WHERE a.id = {AREA_EXPR}) AS storage_area_name,
                       pr.production_date, pr.status, pr.notes,
                       pr.created_by, pr.created_at, pr.submitted_by, pr.submitted_at,
                       (SELECT os.signer_name FROM operator_signoffs os
                        WHERE os.entity_type = 'production_run' AND os.entity_id = pr.id
                          AND os.action = 'production_run.submit'
                        ORDER BY os.signed_at DESC LIMIT 1) AS submitted_by_name,
                       (SELECT COUNT(*) FROM production_run_items pri
                        WHERE pri.run_id = pr.id AND pri.quantity <> 0) AS item_count,
                       (SELECT COUNT(*) FROM production_run_items pri
                        WHERE pri.run_id = pr.id AND pri.corrected_at IS NOT NULL) AS corrected_count,
                       (SELECT COUNT(DISTINCT e.product_id) FROM inventory_count_entries e
                        WHERE e.inventory_submission_id = pr.inventory_submission_id
                          AND e.superseded_at IS NULL) AS end_count,
                       (SELECT COUNT(*) FROM production_qc_checks q
                        WHERE q.run_id = pr.id) AS qc_count,
                       (SELECT COUNT(*) FROM production_qc_checks q
                        WHERE q.run_id = pr.id AND q.result IN ('low', 'high')) AS qc_flags
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
    storage_area_id: the area the run is FOR (default Main).
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
            area = resolve_area(conn, location_id, data.get('storage_area_id'))
            row = conn.execute(text("""
                INSERT INTO production_runs (template_id, location_id, production_date,
                                             status, notes, created_by, storage_area_id)
                VALUES (:tid, :lid, CAST(:d AS date), 'draft', :notes, :by, :area)
                RETURNING id
            """), {'tid': template_id, 'lid': location_id, 'd': prod_date,
                   'notes': data.get('notes'), 'by': g.user.get('email'),
                   'area': area['id'] if area else None}).fetchone()
        return jsonify({'id': row.id}), 201
    except CommissaryAccessError as e:
        return _access_response(e)
    except AreaError as e:
        return jsonify({'error': str(e)}), e.status


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


def _end_lines(conn, inventory_submission_id):
    """The current lines of a run's End Inv inventory (as entered + base)."""
    if not inventory_submission_id:
        return []
    rows = conn.execute(text("""
        SELECT e.product_id, p.name AS product_name, e.unit_id, u.name AS unit_name,
               e.quantity, e.base_quantity, e.base_unit_id, bu.name AS base_unit
        FROM inventory_count_entries e
        JOIN products p ON p.id = e.product_id
        LEFT JOIN units u  ON u.id  = e.unit_id
        LEFT JOIN units bu ON bu.id = e.base_unit_id
        WHERE e.inventory_submission_id = :sid AND e.superseded_at IS NULL
        ORDER BY e.product_id, e.unit_id
    """), {'sid': inventory_submission_id}).mappings().all()
    return [dict(r, quantity=_num(r['quantity']), base_quantity=_num(r['base_quantity']))
            for r in rows]


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
            end_lines = _end_lines(conn, run['inventory_submission_id'])

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

            # Products on this run (made or counted) that the template no longer has.
            extra = {}
            for l in lines:
                if l['product_id'] not in on_template:
                    extra[l['product_id']] = {
                        'product_id': l['product_id'], 'product_name': l['product_name'],
                        'category': None, 'unit_id': l['unit_id'], 'unit_name': l['unit_name'],
                        'base_unit_id': l['base_unit_id'], 'base_unit': l['base_unit'],
                        'line': l, 'not_on_template': True}
            for e in end_lines:
                if e['product_id'] not in on_template and e['product_id'] not in extra:
                    extra[e['product_id']] = {
                        'product_id': e['product_id'], 'product_name': e['product_name'],
                        'category': None, 'unit_id': e['unit_id'], 'unit_name': e['unit_name'],
                        'base_unit_id': e['base_unit_id'], 'base_unit': e['base_unit'],
                        'line': None, 'not_on_template': True}
            if extra:
                sections.append({'id': 'other', 'name': 'Other products',
                                 'items': sorted(extra.values(), key=lambda x: x['product_name'] or '')})

            # End Inv per item: the line in the item's unit is the box; lines in any
            # other unit (e.g. corrected from the Inventories page) are listed under it.
            ends = {}
            for e in end_lines:
                ends.setdefault(e['product_id'], []).append(e)
            for s in sections:
                for it in s['items']:
                    mine = ends.get(it['product_id'], [])
                    box = next((e for e in mine if e['unit_id'] == it['unit_id']), None)
                    it['end_quantity'] = box['quantity'] if box else None
                    it['end_other'] = [{'quantity': e['quantity'], 'unit_name': e['unit_name']}
                                       for e in mine if e is not box]
                    it['end_base'] = (round(sum(e['base_quantity'] for e in mine), 4)
                                      if mine else None)

            # What other submitted runs made today, per product (base units).
            others = conn.execute(text(f"""
                SELECT pri.product_id, pri.base_unit_id, bu.name AS base_unit,
                       SUM(pri.base_quantity) AS base_total, COUNT(DISTINCT pr.id) AS runs
                FROM production_runs pr
                JOIN production_run_items pri ON pri.run_id = pr.id
                LEFT JOIN units bu ON bu.id = pri.base_unit_id
                WHERE pr.location_id = :lid AND pr.production_date = :d
                  AND pr.status = 'submitted' AND pr.id <> :id
                  AND {AREA_EXPR} IS NOT DISTINCT FROM CAST(:area AS integer)
                GROUP BY pri.product_id, pri.base_unit_id, bu.name
            """), {'lid': run['location_id'], 'd': run['production_date'], 'id': run_id,
                   'area': run['storage_area_id']}).fetchall()

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

            # QC: the product's settings (when enabled) and this run's weights.
            all_pids = [it['product_id'] for s in sections for it in s['items']]
            specs  = load_specs(conn, all_pids)
            checks = load_checks(conn, run_id)
            for s in sections:
                for it in s['items']:
                    spec = specs.get(it['product_id'])
                    it['qc_spec']  = spec if spec and spec['enabled'] else None
                    it['qc_check'] = checks.get(it['product_id'])
            # Made by (typed names) + names used before at this commissary, as suggestions
            made_by = {r.product_id: r.made_by for r in conn.execute(text("""
                SELECT product_id, made_by FROM production_run_made_by WHERE run_id = :id
            """), {'id': run_id}).fetchall()}
            for s in sections:
                for it in s['items']:
                    it['made_by'] = made_by.get(it['product_id'])
            run['made_by_suggestions'] = [r.made_by for r in conn.execute(text("""
                SELECT m.made_by, COUNT(*) AS n, MAX(m.updated_at) AS last_used
                FROM production_run_made_by m
                JOIN production_runs pr ON pr.id = m.run_id
                WHERE pr.location_id = :lid AND m.updated_at >= NOW() - INTERVAL '120 days'
                GROUP BY m.made_by
                ORDER BY COUNT(*) DESC, MAX(m.updated_at) DESC
                LIMIT 60
            """), {'lid': run['location_id']}).fetchall()]

            run['qc_samples'] = QC_SAMPLES
            run['qc_flags'] = sum(1 for c in checks.values() if c['result'] in ('low', 'high'))

            # Who signed this run (submit, corrections), newest first
            run['signoffs'] = [dict(r) for r in conn.execute(text("""
                SELECT action, signer_name, toast_employee_guid, login_email, note, signed_at
                FROM operator_signoffs
                WHERE entity_type = 'production_run' AND entity_id = :id
                ORDER BY signed_at DESC, id DESC
            """), {'id': run_id}).mappings().all()]
            sub = next((s for s in run['signoffs'] if s['action'] == 'production_run.submit'), None)
            run['submitted_by_name'] = sub['signer_name'] if sub else None

        run['sections']   = sections
        run['lines']      = lines
        run['end_counted'] = len({e['product_id'] for e in end_lines})
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
    Body: {entries: [{product_id, quantity, end_quantity, qc_weights, made_by}], correction_notes?}
    One entry per product row on the sheet.

    quantity (Made), blank = null / '':
      draft      -> the line is removed
      submitted  -> treated as 0 (a correction; the earlier value is kept)
    end_quantity (End Inv), only when the key is sent; blank = not counted
      (the inventory line is removed, also on a submitted run).

    made_by, only when the key is sent: the name as typed (trimmed, spaces
      squeezed, up to 80 characters); blank removes it.
    qc_weights (QC), only when the key is sent: up to QC_SAMPLES scale readings;
      blanks are skipped, all blank removes the check. Needs QC set up on the
      product (unless the run already has weights for it).

    The unit is decided here: the run line's own unit if it exists, else the
    product's unit on the run's template. End Inv uses the same unit. A product
    that is neither on the run nor on the template is refused.
    Every unit must convert to the product's base unit, or nothing is saved
    (missing_conversions lists what is missing).
    """
    data    = request.get_json(force=True) or {}
    entries = data.get('entries') or []
    notes   = (data.get('correction_notes') or '').strip() or None
    user    = g.user.get('email')

    def parse_qty(q):
        if q is None or (isinstance(q, str) and not q.strip()):
            return None
        try:
            q = round(float(q), 4)
        except (TypeError, ValueError):
            raise ValueError(f'Not a number: {q}')
        if q < 0:
            raise ValueError('Amounts cannot be negative')
        return q

    def parse_weights(ws):
        if not isinstance(ws, list):
            raise ValueError('QC weights must be a list')
        out = []
        for w in ws[:QC_SAMPLES]:
            if w is None or (isinstance(w, str) and not w.strip()):
                continue
            try:
                w = round(float(w), 3)
            except (TypeError, ValueError):
                raise ValueError(f'Not a weight: {w}')
            if w <= 0 or w > 1000:
                raise ValueError('QC weights must be more than 0 (and under 1000)')
            out.append(w)
        return out or None

    made, ends, qcw, mby = {}, {}, {}, {}
    try:
        for e in entries:
            try:
                pid = int(e.get('product_id'))
            except (TypeError, ValueError):
                return jsonify({'error': 'Every entry needs a product_id'}), 400
            if 'quantity' in e:
                made[pid] = parse_qty(e.get('quantity'))
            if 'end_quantity' in e:
                ends[pid] = parse_qty(e.get('end_quantity'))
            if 'qc_weights' in e:
                qcw[pid] = parse_weights(e.get('qc_weights'))
            if 'made_by' in e:
                name = ' '.join(str(e.get('made_by') or '').split())
                if len(name) > 80:
                    raise ValueError('Made by names can be up to 80 characters')
                mby[pid] = name or None
    except ValueError as err:
        return jsonify({'error': str(err)}), 400

    try:
        with get_engine().begin() as conn:
            run = _load_run(conn, run_id)
            if not _can_edit(run):
                return jsonify({'error': 'This production run was submitted. Only an admin or '
                                         'commissary GM can change it.'}), 403
            submitted = run['status'] == 'submitted'

            existing = {r.product_id: r for r in conn.execute(text("""
                SELECT product_id, quantity, unit_id
                FROM production_run_items WHERE run_id = :id
            """), {'id': run_id}).fetchall()}
            template_units = {r.product_id: r.unit_id for r in conn.execute(text("""
                SELECT DISTINCT ON (pti.product_id) pti.product_id, pti.unit_id
                FROM production_template_items pti
                JOIN production_template_sections pts ON pts.id = pti.section_id
                WHERE pts.template_id = :tid
                ORDER BY pti.product_id, pts.sort_order, pti.sort_order, pti.id
            """), {'tid': run['template_id']}).fetchall()} if run['template_id'] else {}

            inv_id = run['inventory_submission_id']
            end_current = {}                     # (pid, uid) -> quantity, current End Inv lines
            if inv_id:
                for r in conn.execute(text("""
                    SELECT product_id, unit_id, quantity FROM inventory_count_entries
                    WHERE inventory_submission_id = :sid AND superseded_at IS NULL
                """), {'sid': inv_id}).fetchall():
                    end_current[(r.product_id, r.unit_id)] = float(r.quantity)
            end_units = {}
            for (pid, uid) in end_current:
                end_units.setdefault(pid, uid)

            # The unit of each product row on the sheet (same rule as GET).
            unit_for = {}
            for pid in set(made) | set(ends) | set(qcw) | set(mby):
                if pid in existing:
                    unit_for[pid] = existing[pid].unit_id
                elif pid in template_units:
                    unit_for[pid] = template_units[pid]
                elif pid in end_units:
                    unit_for[pid] = end_units[pid]
                elif (made.get(pid) is not None or ends.get(pid) is not None
                      or qcw.get(pid) or mby.get(pid)):
                    return jsonify({'error': f'Product {pid} is not on this production template'}), 400

            pids  = set(unit_for)
            bases = load_base_units(conn, pids)
            conv  = load_conversion_map(conn, pids, set(unit_for.values()), set(bases.values()))

            def factor_for(pid):
                return base_factor(conv, unit_for[pid], bases.get(pid), pid)

            missing = []

            # ── Made ───────────────────────────────────────────────────────────
            writes, removes = [], []
            for pid, qty in made.items():
                if pid not in unit_for:
                    continue                      # blank box for a product with no line
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
                f = factor_for(pid)
                if f is None:
                    missing.append((pid, unit_for[pid]))
                    continue
                writes.append({'pid': pid, 'qty': qty, 'uid': unit_for[pid],
                               'bq': round(qty * f, 4), 'bu': bases.get(pid)})

            # ── End Inv (inventory lines in the row's unit) ────────────────────
            end_remove, end_write = [], []
            for pid, qty in ends.items():
                if pid not in unit_for:
                    continue
                key = (pid, unit_for[pid])
                cur = end_current.get(key)
                if qty is None:
                    if cur is not None:
                        end_remove.append(key)
                    continue
                if cur == qty:
                    continue
                f = factor_for(pid)
                if f is None:
                    missing.append(key)
                    continue
                end_write.append({'product_id': pid, 'unit_id': unit_for[pid], 'quantity': qty,
                                  'base_quantity': round(qty * f, 4), 'base_unit_id': bases.get(pid)})

            if missing:
                missing = list(dict.fromkeys(missing))
                names = conn.execute(text("""
                    SELECT m.pid AS product_id, m.uid AS unit_id, p.name AS product_name,
                           u.name AS unit_name, bu.name AS base_unit
                    FROM unnest(CAST(:pids AS bigint[]), CAST(:uids AS integer[])) AS m(pid, uid)
                    JOIN products p ON p.id = m.pid
                    LEFT JOIN units u  ON u.id  = m.uid
                    LEFT JOIN units bu ON bu.id = p.base_unit_id
                """), {'pids': [m[0] for m in missing],
                       'uids': [m[1] for m in missing]}).mappings().all()
                return jsonify({'error': 'Some units have no conversion to the product\'s base unit. '
                                         'Nothing was saved.',
                                'missing_conversions': [dict(n) for n in names]}), 400

            # ── QC weights ─────────────────────────────────────────────────────
            qc_write, qc_remove = [], []
            if qcw:
                cur_checks = load_checks(conn, run_id)
                specs = load_specs(conn, list(qcw))
                for pid, ws in qcw.items():
                    if pid not in unit_for:
                        continue
                    cur = cur_checks.get(pid)
                    if ws is None:
                        if cur:
                            qc_remove.append(pid)
                        continue
                    if cur and cur['weights'] == ws:
                        continue                  # unchanged
                    if cur:
                        snap = {'package_unit_id': cur['package_unit_id'], 'target_weight': cur['target_weight'],
                                'tolerance': cur['tolerance'], 'scale_unit': cur['scale_unit']}
                    else:
                        spec = specs.get(pid)
                        if not spec or not spec['enabled']:
                            return jsonify({'error': f'Product {pid} is not set up for QC weights'}), 400
                        snap = {'package_unit_id': spec['package_unit_id'], 'target_weight': spec['target_weight'],
                                'tolerance': spec['tolerance'], 'scale_unit': spec['scale_unit']}
                    avg, result = evaluate(ws, snap['target_weight'], snap['tolerance'])
                    qc_write.append(dict(snap, pid=pid, weights=ws, avg=avg, result=result))

            # ── Made by (typed names) ──────────────────────────────────────────
            mb_write, mb_remove = [], []
            if mby:
                cur_mb = {r.product_id: r.made_by for r in conn.execute(text("""
                    SELECT product_id, made_by FROM production_run_made_by WHERE run_id = :id
                """), {'id': run_id}).fetchall()}
                for pid, name in mby.items():
                    if pid not in unit_for:
                        continue
                    if name is None:
                        if pid in cur_mb:
                            mb_remove.append(pid)
                    elif cur_mb.get(pid) != name:
                        mb_write.append({'pid': pid, 'name': name})

            # A change to a SUBMITTED run is a correction: it is signed (who changed it).
            who = user
            signer = None
            if submitted and (writes or removes or end_write or end_remove or qc_write or qc_remove
                              or mb_write or mb_remove):
                signer = signer_for(conn, run['location_id'])
                who = signer['name']

            # ── Write Made ─────────────────────────────────────────────────────
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
                    """), dict(w, id=run_id, user=who, notes=notes))
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

            # ── Write End Inv through the inventory rules ──────────────────────
            if end_write or end_remove:
                if not inv_id:
                    inv_id = _create_run_inventory(conn, run, user)
                retire = end_remove + [(r['product_id'], r['unit_id']) for r in end_write
                                       if (r['product_id'], r['unit_id']) in end_current]
                supersede_line_pairs(conn, inv_id, retire, who)
                insert_lines(conn, inv_id, end_write, who)
                if submitted:
                    changed = list({k[0] for k in end_remove} | {r['product_id'] for r in end_write})
                    adopt_day_counts(conn, run['location_id'], run['production_date'])
                    sync_counts_from_entries(conn, inv_id, who, changed,
                                             mark_changes=True, correction_notes=notes)
                    refresh_day_counts(conn, run['location_id'], run['production_date'], changed)
                conn.execute(text("""
                    UPDATE inventory_submissions SET updated_at = NOW() WHERE id = :id
                """), {'id': inv_id})

            # ── Write Made by ──────────────────────────────────────────────────
            if mb_remove:
                conn.execute(text("""
                    DELETE FROM production_run_made_by WHERE run_id = :id AND product_id = ANY(:pids)
                """), {'id': run_id, 'pids': mb_remove})
            for m in mb_write:
                conn.execute(text("""
                    INSERT INTO production_run_made_by (run_id, product_id, made_by, entered_by, updated_at)
                    VALUES (:id, :pid, :name, :who, NOW())
                    ON CONFLICT (run_id, product_id) DO UPDATE SET
                        made_by = EXCLUDED.made_by, entered_by = EXCLUDED.entered_by, updated_at = NOW()
                """), dict(m, id=run_id, who=who))

            # ── Write QC weights ───────────────────────────────────────────────
            if qc_remove:
                conn.execute(text("""
                    DELETE FROM production_qc_checks WHERE run_id = :id AND product_id = ANY(:pids)
                """), {'id': run_id, 'pids': qc_remove})
            for q in qc_write:
                conn.execute(text("""
                    INSERT INTO production_qc_checks (
                        run_id, product_id, weights, average_weight, result,
                        package_unit_id, target_weight, tolerance, scale_unit,
                        entered_by, updated_by
                    ) VALUES (
                        :id, :pid, CAST(:weights AS numeric[]), :avg, :result,
                        :package_unit_id, :target_weight, :tolerance, :scale_unit, :who, :who
                    )
                    ON CONFLICT (run_id, product_id) DO UPDATE SET
                        weights        = EXCLUDED.weights,
                        average_weight = EXCLUDED.average_weight,
                        result         = EXCLUDED.result,
                        updated_by     = EXCLUDED.updated_by,
                        updated_at     = NOW()
                """), dict(q, id=run_id, who=who))

            if signer:
                record_signoff(conn, signer, 'production_run.correct', 'production_run', run_id,
                               run['location_id'], note=notes)
            conn.execute(text("""
                UPDATE production_runs SET updated_at = NOW() WHERE id = :id
            """), {'id': run_id})
        return jsonify({'status': 'ok',
                        'changed': len(writes) + len(removes) + len(end_write) + len(end_remove)
                                   + len(qc_write) + len(qc_remove) + len(mb_write) + len(mb_remove)})
    except OperatorRequired:
        return operator_required_response()
    except CommissaryAccessError as e:
        return _access_response(e)


def _create_run_inventory(conn, run, user):
    """
    The commissary inventory behind a run's End Inv boxes: same location and
    date as the run. Draft while the run is a draft; a run that is already
    submitted (its inventory was deleted from the Inventories page) gets a
    submitted one straight away.
    """
    submitted = run['status'] == 'submitted'
    inv_id = conn.execute(text("""
        INSERT INTO inventory_submissions (
            template_id, location_id, count_date, source, status,
            submitted_by, submitted_at, notes, storage_area_id
        ) VALUES (
            NULL, :lid, CAST(:d AS date), 'production', :status,
            :by, CASE WHEN :submitted THEN NOW() END, :notes, :area
        ) RETURNING id
    """), {'lid': run['location_id'], 'd': run['production_date'], 'area': run.get('storage_area_id'),
           'status': 'submitted' if submitted else 'draft', 'submitted': submitted,
           'by': user, 'notes': f'End inventory from production run #{run["id"]}'}).fetchone().id
    conn.execute(text("""
        UPDATE production_runs SET inventory_submission_id = :inv WHERE id = :id
    """), {'inv': inv_id, 'id': run['id']})
    run['inventory_submission_id'] = inv_id
    return inv_id


def _inventory_product_ids(conn, inv_id):
    rows = conn.execute(text("""
        SELECT product_id FROM inventory_submission_counts WHERE inventory_submission_id = :id
        UNION
        SELECT product_id FROM inventory_counts WHERE inventory_submission_id = :id
    """), {'id': inv_id}).fetchall()
    return [r.product_id for r in rows]


def _delete_run_inventory(conn, run):
    """Remove a run's inventory; the day's count falls back to the next submitted one."""
    inv_id = run['inventory_submission_id']
    if not inv_id:
        return
    adopt_day_counts(conn, run['location_id'], run['production_date'])
    pids = _inventory_product_ids(conn, inv_id)
    conn.execute(text("DELETE FROM inventory_counts WHERE inventory_submission_id = :id"), {'id': inv_id})
    conn.execute(text("DELETE FROM inventory_submissions WHERE id = :id"), {'id': inv_id})
    refresh_day_counts(conn, run['location_id'], run['production_date'], pids)


@bp.route('/production-runs/<int:run_id>/submit', methods=['POST'])
@comm_required
def submit_production_run(run_id):
    """
    Submit a draft: it needs at least one amount made above 0 or one End Inv.
    Its End Inv inventory is submitted with it and becomes the commissary's
    count for the day (latest submitted wins, product by product).
    """
    user = g.user.get('email')
    try:
        with get_engine().begin() as conn:
            run = _load_run(conn, run_id)
            if run['status'] != 'draft':
                return jsonify({'error': 'This production run was already submitted'}), 400
            made = conn.execute(text("""
                SELECT COUNT(*) AS n FROM production_run_items WHERE run_id = :id AND quantity > 0
            """), {'id': run_id}).fetchone().n
            inv_id = run['inventory_submission_id']
            counted = conn.execute(text("""
                SELECT COUNT(*) AS n FROM inventory_count_entries
                WHERE inventory_submission_id = :sid AND superseded_at IS NULL
            """), {'sid': inv_id}).fetchone().n if inv_id else 0
            if not made and not counted:
                return jsonify({'error': 'Enter at least one amount made or one End Inv before submitting'}), 400
            signer = signer_for(conn, run['location_id'])      # who filled out and submits the run
            record_signoff(conn, signer, 'production_run.submit', 'production_run', run_id,
                           run['location_id'])

            conn.execute(text("""
                UPDATE production_runs
                SET status = 'submitted', submitted_by = :by, submitted_at = NOW(), updated_at = NOW()
                WHERE id = :id AND status = 'draft'
            """), {'id': run_id, 'by': user})

            if inv_id and counted:
                adopt_day_counts(conn, run['location_id'], run['production_date'])
                conn.execute(text("""
                    UPDATE inventory_submissions
                    SET status = 'submitted', submitted_by = :by, submitted_at = NOW(), updated_at = NOW()
                    WHERE id = :id
                """), {'id': inv_id, 'by': user})
                sync_counts_from_entries(conn, inv_id, user, mark_changes=False)
                refresh_day_counts(conn, run['location_id'], run['production_date'],
                                   _inventory_product_ids(conn, inv_id))
            elif inv_id:
                _delete_run_inventory(conn, run)      # every End Inv was cleared: no empty inventory
        return jsonify({'status': 'ok', 'end_counted': counted, 'signed_by': signer['name']})
    except OperatorRequired:
        return operator_required_response()
    except CommissaryAccessError as e:
        return _access_response(e)


@bp.route('/production-runs/<int:run_id>', methods=['DELETE'])
@comm_required
def delete_production_run(run_id):
    """
    Drafts: anyone at that commissary. Submitted: PRODUCTION_EDIT_ROLES only.
    The run's End Inv inventory goes with it.
    """
    try:
        with get_engine().begin() as conn:
            run = _load_run(conn, run_id)
            if run['status'] == 'submitted' and not can_edit_submitted_production():
                return jsonify({'error': 'Only an admin or commissary GM can delete a submitted '
                                         'production run'}), 403
            _delete_run_inventory(conn, run)
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
    area_id   = request.args.get('storage_area_id', type=int)
    area_sql  = f'AND {AREA_EXPR} = :area' if area_id else ''
    try:
        with get_engine().connect() as conn:
            location_id = resolve_commissary_location(conn, request.args.get('location_id'))
            rows = conn.execute(text(f"""
                SELECT pr.production_date, pri.product_id, p.name AS product_name,
                       c.name AS category,
                       pri.base_unit_id, bu.name AS base_unit,
                       SUM(pri.base_quantity) AS base_total,
                       COUNT(DISTINCT pr.id)  AS runs,
                       COUNT(DISTINCT pri.unit_id) AS unit_count,
                       MIN(pri.unit_id) AS unit_id,
                       SUM(pri.quantity) AS quantity_total,
                       BOOL_OR(pri.corrected_at IS NOT NULL) AS corrected,
                       STRING_AGG(DISTINCT mb.made_by, ', ') AS made_by
                FROM production_runs pr
                JOIN production_run_items pri ON pri.run_id = pr.id
                LEFT JOIN production_run_made_by mb
                       ON mb.run_id = pr.id AND mb.product_id = pri.product_id
                JOIN products p ON p.id = pri.product_id
                LEFT JOIN product_categories c ON c.id = p.category_id
                LEFT JOIN units bu ON bu.id = pri.base_unit_id
                WHERE pr.location_id = :lid AND pr.status = 'submitted'
                  AND pr.production_date BETWEEN CAST(:df AS date) AND CAST(:dt AS date)
                  {area_sql}
                GROUP BY pr.production_date, pri.product_id, p.name, c.name,
                         pri.base_unit_id, bu.name
                HAVING SUM(pri.base_quantity) <> 0
                ORDER BY pr.production_date DESC, c.name NULLS LAST, p.name
            """), {'lid': location_id, 'df': date_from, 'dt': date_to, 'area': area_id}).mappings().all()
            unit_names = {r.id: r.name for r in conn.execute(text("""
                SELECT id, name FROM units WHERE id = ANY(:ids)
            """), {'ids': list({r['unit_id'] for r in rows}) or [0]}).fetchall()}
            run_counts = conn.execute(text(f"""
                SELECT pr.production_date,
                       COUNT(*) FILTER (WHERE pr.status = 'submitted') AS submitted,
                       COUNT(*) FILTER (WHERE pr.status = 'draft')     AS drafts
                FROM production_runs pr
                WHERE pr.location_id = :lid
                  AND pr.production_date BETWEEN CAST(:df AS date) AND CAST(:dt AS date)
                  {area_sql}
                GROUP BY pr.production_date
            """), {'lid': location_id, 'df': date_from, 'dt': date_to, 'area': area_id}).mappings().all()

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
                'made_by':      r['made_by'],
            })
        return jsonify({
            'location_id': location_id,
            'date_from':   date_from,
            'date_to':     date_to,
            'days':        sorted(days.values(), key=lambda d: d['date'], reverse=True),
        })
    except CommissaryAccessError as e:
        return _access_response(e)
