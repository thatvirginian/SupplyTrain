# =============================================================================
# backend/features/commissary/storage_area_routes.py
# =============================================================================
# Storage areas of a commissary (storage_areas_plan.md, step 1):
#   - the list of areas (any page that lets you pick an area),
#   - adding / changing areas (admin: Storage Areas page),
#   - the Commissary Stock overview: per product, each area's latest count
#     on or before a date, and the total of the areas.
#
# Endpoints in this file:
#   GET  /api/storage-areas                 list_storage_areas
#   POST /api/storage-areas                 create_storage_area
#   PUT  /api/storage-areas/<int:area_id>   update_storage_area
#   GET  /api/storage-areas/stock           storage_area_stock
# =============================================================================

from datetime import datetime
import os
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text

from core.auth import admin_required, staff_required, comm_required, _is_admin, _get_user_location
from core.database import get_engine
from core.units import load_conversion_map, base_factor
from features.commissary.commissary_access import (
    CommissaryAccessError, is_commissary_location, resolve_commissary_location,
)
from features.commissary.storage_areas import list_areas, ensure_main

bp = Blueprint('storage_area_routes', __name__, url_prefix='/api')

STORE_TZ = os.environ.get('STORE_TIMEZONE', 'America/New_York')


def _today_local():
    return datetime.now(ZoneInfo(STORE_TZ)).date().isoformat()


def _num(v):
    return None if v is None else float(v)


@bp.route('/storage-areas', methods=['GET'])
@staff_required
def list_storage_areas():
    """
    Areas of a location, Main first ([] when the location has no areas, e.g. a store).
    Admins: ?location_id= (any location), ?include_inactive=true. Everyone else:
    their own location, active areas only.
    """
    with get_engine().connect() as conn:
        if _is_admin():
            location_id = request.args.get('location_id')
            if not location_id:
                return jsonify({'error': 'location_id is required'}), 400
            inactive = request.args.get('include_inactive', 'false').lower() == 'true'
        else:
            location_id = _get_user_location(conn)
            if not location_id:
                return jsonify([])
            inactive = False
        return jsonify(list_areas(conn, location_id, include_inactive=inactive))


def _clean_name(name):
    name = ' '.join(str(name or '').split())
    if not name:
        raise ValueError('Give the area a name')
    if len(name) > 80:
        raise ValueError('Area names can be up to 80 characters')
    return name


@bp.route('/storage-areas', methods=['POST'])
@admin_required
def create_storage_area():
    """Add a site to a commissary (its Main area is created too when missing)."""
    data = request.get_json(force=True) or {}
    location_id = data.get('location_id')
    try:
        name = _clean_name(data.get('name'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    with get_engine().begin() as conn:
        if not is_commissary_location(conn, location_id):
            return jsonify({'error': 'Storage areas are for commissaries'}), 400
        ensure_main(conn, location_id, g.user.get('email'))
        if conn.execute(text("""
            SELECT 1 FROM storage_areas WHERE location_id = :lid AND lower(name) = lower(:name)
        """), {'lid': str(location_id), 'name': name}).fetchone():
            return jsonify({'error': f'This commissary already has an area named "{name}"'}), 409
        nxt = conn.execute(text("""
            SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM storage_areas WHERE location_id = :lid
        """), {'lid': str(location_id)}).fetchone().n
        new_id = conn.execute(text("""
            INSERT INTO storage_areas (location_id, name, kind, restocked, notes, sort_order, created_by)
            VALUES (:lid, :name, 'site', :restocked, :notes, :so, :by) RETURNING id
        """), {'lid': str(location_id), 'name': name, 'restocked': bool(data.get('restocked', True)),
               'notes': (data.get('notes') or '').strip() or None, 'so': nxt,
               'by': g.user.get('email')}).fetchone().id
    return jsonify({'id': new_id}), 201


@bp.route('/storage-areas/<int:area_id>', methods=['PUT'])
@admin_required
def update_storage_area(area_id):
    """Rename, restocked yes/no, notes, active, sort order. Main cannot be switched off."""
    data = request.get_json(force=True) or {}
    with get_engine().begin() as conn:
        area = conn.execute(text("""
            SELECT id, location_id, kind FROM storage_areas WHERE id = :id
        """), {'id': area_id}).mappings().fetchone()
        if not area:
            return jsonify({'error': 'Storage area not found'}), 404
        name = None
        if 'name' in data:
            try:
                name = _clean_name(data.get('name'))
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
            if conn.execute(text("""
                SELECT 1 FROM storage_areas
                WHERE location_id = :lid AND lower(name) = lower(:name) AND id <> :id
            """), {'lid': area['location_id'], 'name': name, 'id': area_id}).fetchone():
                return jsonify({'error': f'This commissary already has an area named "{name}"'}), 409
        if area['kind'] == 'main' and data.get('active') is False:
            return jsonify({'error': 'Main cannot be switched off'}), 400
        conn.execute(text("""
            UPDATE storage_areas SET
                name       = COALESCE(:name, name),
                restocked  = COALESCE(:restocked, restocked),
                notes      = CASE WHEN :set_notes THEN :notes ELSE notes END,
                active     = COALESCE(:active, active),
                sort_order = COALESCE(:so, sort_order),
                updated_at = NOW()
            WHERE id = :id
        """), {'id': area_id, 'name': name,
               'restocked': data.get('restocked') if 'restocked' in data else None,
               'set_notes': 'notes' in data, 'notes': (data.get('notes') or '').strip() or None,
               'active': data.get('active') if 'active' in data else None,
               'so': data.get('sort_order')})
    return jsonify({'status': 'ok'})


@bp.route('/storage-areas/stock', methods=['GET'])
@comm_required
def storage_area_stock():
    """
    Commissary Stock overview. Per product: each area's latest count ON OR BEFORE
    ?date (default today) with its date, and the total over the areas.
    Shown in the product's inventory unit when it has one that converts, else base.
    Params: location_id (admins), date, search.
    """
    as_of = request.args.get('date') or _today_local()
    try:
        with get_engine().connect() as conn:
            location_id = resolve_commissary_location(conn, request.args.get('location_id'))
            areas = list_areas(conn, location_id)
            if not areas:
                return jsonify({'location_id': location_id, 'date': as_of, 'areas': [], 'products': []})
            rows = conn.execute(text("""
                SELECT DISTINCT ON (c.storage_area_id, c.product_id)
                       c.storage_area_id, c.product_id, c.count_date,
                       c.base_quantity, c.base_unit_id, c.inventory_submission_id
                FROM inventory_area_counts c
                JOIN storage_areas a ON a.id = c.storage_area_id AND a.active
                WHERE c.location_id = :lid AND c.count_date <= CAST(:d AS date)
                  AND c.base_quantity IS NOT NULL
                ORDER BY c.storage_area_id, c.product_id, c.count_date DESC
            """), {'lid': location_id, 'd': as_of}).mappings().all()
            pids = list({r['product_id'] for r in rows})
            prods = {r['id']: dict(r) for r in conn.execute(text("""
                SELECT p.id, p.name, c.name AS category, p.base_unit_id, bu.name AS base_unit,
                       p.inventory_unit_id, iu.name AS inventory_unit
                FROM products p
                LEFT JOIN product_categories c ON c.id = p.category_id
                LEFT JOIN units bu ON bu.id = p.base_unit_id
                LEFT JOIN units iu ON iu.id = p.inventory_unit_id
                WHERE p.id = ANY(:ids)
            """), {'ids': pids or [0]}).mappings().all()}
            units = ({p['inventory_unit_id'] for p in prods.values()} | {r['base_unit_id'] for r in rows})
            units.discard(None)
            conv = load_conversion_map(conn, pids, units, {p['base_unit_id'] for p in prods.values()})
    except CommissaryAccessError as e:
        return jsonify({'error': str(e)}), e.status

    search = (request.args.get('search') or '').strip().lower()
    out = {}
    for r in rows:
        p = prods.get(r['product_id'])
        if not p or (search and search not in p['name'].lower()):
            continue
        pid = r['product_id']
        disp_id, disp_name = p['base_unit_id'], p['base_unit']
        to_disp = 1.0
        if p['inventory_unit_id']:
            f = base_factor(conv, p['inventory_unit_id'], p['base_unit_id'], pid)
            if f:
                disp_id, disp_name, to_disp = p['inventory_unit_id'], p['inventory_unit'], f
        row_to_base = base_factor(conv, r['base_unit_id'], p['base_unit_id'], pid)
        o = out.setdefault(pid, {'product_id': pid, 'product_name': p['name'], 'category': p['category'],
                                 'unit_name': disp_name, 'base_unit': p['base_unit'],
                                 'areas': {}, 'total': 0.0, 'total_base': 0.0, 'missing_conversion': False})
        if row_to_base is None:
            o['missing_conversion'] = True
            o['areas'][str(r['storage_area_id'])] = {'quantity': None, 'date': str(r['count_date']),
                                                     'inventory_submission_id': r['inventory_submission_id']}
            continue
        base = float(r['base_quantity']) * row_to_base
        o['areas'][str(r['storage_area_id'])] = {
            'quantity': round(base / to_disp, 2), 'base_quantity': round(base, 4),
            'date': str(r['count_date']), 'inventory_submission_id': r['inventory_submission_id']}
        o['total_base'] += base
        o['total'] += base / to_disp
    products = sorted(out.values(), key=lambda x: ((x['category'] or '~').lower(), x['product_name'].lower()))
    for o in products:
        o['total'] = round(o['total'], 2)
        o['total_base'] = round(o['total_base'], 4)
    return jsonify({'location_id': location_id, 'date': as_of, 'areas': areas, 'products': products})
