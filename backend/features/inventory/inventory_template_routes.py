# =============================================================================
# backend/features/inventory/inventory_template_routes.py
# =============================================================================
# Inv Templates (admin): templates for inventory counts. Templates, sections, products, count units, locations.
#
# Endpoints in this file:
#   GET     /api/inventory-templates                                            list_inventory_templates
#   POST    /api/inventory-templates                                            create_inventory_template
#   GET     /api/inventory-templates/<int:template_id>                          get_inventory_template
#   PUT     /api/inventory-templates/<int:template_id>                          update_inventory_template
#   POST    /api/inventory-templates/<int:template_id>/toggle-active            toggle_inventory_template
#   POST    /api/inventory-templates/<int:template_id>/sort                     sort_inventory_template
#   POST    /api/inventory-templates/<int:template_id>/locations                add_inventory_template_location
#   DELETE  /api/inventory-templates/<int:template_id>/locations/<location_id>  remove_inventory_template_location
#   POST    /api/inventory-sections                                             create_inventory_section
#   PUT     /api/inventory-sections/<int:section_id>                            update_inventory_section
#   DELETE  /api/inventory-sections/<int:section_id>                            delete_inventory_section
#   POST    /api/inventory-sections/<int:section_id>/items                      add_inventory_section_item
#   DELETE  /api/inventory-template-items/<int:item_id>                         delete_inventory_section_item
#   POST    /api/inventory-template-items/<int:item_id>/units                   add_inventory_item_unit
#   DELETE  /api/inventory-template-item-units/<int:unit_id>                    remove_inventory_item_unit
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
import logging

from core.auth import (
    admin_required, staff_required, get_user_location_or_raise,
)
from core.database import get_engine
from core.units import has_base_conversion

logger = logging.getLogger(__name__)

bp = Blueprint('inventory_template_routes', __name__, url_prefix='/api')


# =============================================================================
# Inventory Templates
# =============================================================================

@bp.route('/inventory-templates', methods=['GET'])
@staff_required
def list_inventory_templates():
    roles       = g.user.get('roles', [])
    is_admin    = 'admin' in roles
    location_id = request.args.get('location_id')
    show_inactive = request.args.get('show_inactive', 'false').lower() == 'true'

    with get_engine().connect() as conn:
        if is_admin and not location_id:
            active_filter = '' if show_inactive else 'WHERE it.active = TRUE'
            rows = conn.execute(text(f"""
                SELECT
                    it.id, it.name, it.notes, it.active,
                    it.created_at, it.updated_at,
                    COUNT(DISTINCT itl.location_id) AS location_count,
                    COUNT(DISTINCT its.id)           AS section_count
                FROM inventory_templates it
                LEFT JOIN inventory_template_locations itl ON itl.template_id = it.id
                LEFT JOIN inventory_template_sections  its ON its.template_id = it.id
                {active_filter}
                GROUP BY it.id
                ORDER BY it.name
            """)).mappings().all()
        else:
            if not location_id and not is_admin:
                location_id = get_user_location_or_raise(conn)
            rows = conn.execute(text("""
                SELECT
                    it.id, it.name, it.notes, it.active,
                    it.created_at, it.updated_at,
                    COUNT(DISTINCT its.id) AS section_count
                FROM inventory_templates it
                JOIN inventory_template_locations itl ON itl.template_id = it.id
                LEFT JOIN inventory_template_sections its ON its.template_id = it.id
                WHERE it.active = TRUE
                AND itl.location_id = :location_id
                GROUP BY it.id
                ORDER BY it.name
            """), {'location_id': location_id}).mappings().all()

    return jsonify([dict(r) for r in rows])


@bp.route('/inventory-templates', methods=['POST'])
@admin_required
def create_inventory_template():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO inventory_templates (name, notes, created_by)
                VALUES (:name, :notes, :created_by)
                RETURNING id
            """), {
                'name':       name,
                'notes':      data.get('notes'),
                'created_by': g.user.get('email'),
            })
            template_id = result.fetchone().id
        return jsonify({'id': template_id}), 201
    except Exception as e:
        logger.error(f'create_inventory_template: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-templates/<int:template_id>', methods=['GET'])
@staff_required
def get_inventory_template(template_id):
    with get_engine().connect() as conn:
        template = conn.execute(text("""
            SELECT id, name, notes, active, created_at, updated_at
            FROM inventory_templates WHERE id = :id
        """), {'id': template_id}).mappings().fetchone()

        if not template:
            return jsonify({'error': 'Template not found'}), 404

        sections = conn.execute(text("""
            SELECT
                its.id, its.name, its.sort_order,
                json_agg(
                    json_build_object(
                        'id',           iti.id,
                        'product_id',   iti.product_id,
                        'product_name', p.name,
                        'category',     c.name,
                        'base_unit',    u.name,
                        'base_unit_id', p.base_unit_id,
                        'sort_order',   iti.sort_order
                    ) ORDER BY iti.sort_order
                ) FILTER (WHERE iti.id IS NOT NULL) AS items
            FROM inventory_template_sections its
            LEFT JOIN inventory_template_items iti ON iti.section_id  = its.id
            LEFT JOIN products p                   ON iti.product_id  = p.id
            LEFT JOIN product_categories c         ON p.category_id   = c.id
            LEFT JOIN units u                      ON p.base_unit_id  = u.id
            WHERE its.template_id = :id
            GROUP BY its.id
            ORDER BY its.sort_order
        """), {'id': template_id}).mappings().all()

        # Count units per item
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

        locations = conn.execute(text("""
            SELECT itl.location_id, l.location_name
            FROM inventory_template_locations itl
            JOIN locations l ON l.store_guid::text = itl.location_id
            WHERE itl.template_id = :id
            ORDER BY l.location_name
        """), {'id': template_id}).mappings().all()

    result = dict(template)
    # Merge count units into items
    sections_list = []
    for s in sections:
        sd = dict(s)
        if sd.get('items'):
            for item in sd['items']:
                item['count_units'] = count_units_map.get(item['id'], [])
        sections_list.append(sd)
    result['sections']  = sections_list
    result['locations'] = [dict(l) for l in locations]
    return jsonify(result)


@bp.route('/inventory-templates/<int:template_id>', methods=['PUT'])
@admin_required
def update_inventory_template(template_id):
    data = request.get_json(force=True)
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE inventory_templates SET
                    name       = COALESCE(:name, name),
                    notes      = :notes,
                    active     = COALESCE(:active, active),
                    updated_at = NOW()
                WHERE id = :id
            """), {
                'id':     template_id,
                'name':   data.get('name'),
                'notes':  data.get('notes'),
                'active': data.get('active'),
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'update_inventory_template: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-templates/<int:template_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_inventory_template(template_id):
    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                UPDATE inventory_templates SET active = NOT active, updated_at = NOW()
                WHERE id = :id RETURNING active
            """), {'id': template_id})
            new_active = result.fetchone().active
        return jsonify({'status': 'ok', 'active': new_active})
    except Exception as e:
        logger.error(f'toggle_inventory_template: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-templates/<int:template_id>/sort', methods=['POST'])
@admin_required
def sort_inventory_template(template_id):
    data     = request.get_json(force=True)
    sections = data.get('sections', [])
    try:
        with get_engine().begin() as conn:
            for section in sections:
                conn.execute(text("""
                    UPDATE inventory_template_sections
                    SET sort_order = :sort_order WHERE id = :id
                """), {'id': section['id'], 'sort_order': section['sort_order']})
                for item in section.get('items', []):
                    conn.execute(text("""
                        UPDATE inventory_template_items
                        SET sort_order = :sort_order, section_id = :section_id
                        WHERE id = :id
                    """), {
                        'id':         item['id'],
                        'sort_order': item['sort_order'],
                        'section_id': section['id'],
                    })
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'sort_inventory_template: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-templates/<int:template_id>/locations', methods=['POST'])
@admin_required
def add_inventory_template_location(template_id):
    data = request.get_json(force=True)
    location_id = data.get('location_id')
    if not location_id:
        return jsonify({'error': 'location_id is required'}), 400
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO inventory_template_locations (template_id, location_id)
                VALUES (:template_id, :location_id)
                ON CONFLICT DO NOTHING
            """), {'template_id': template_id, 'location_id': location_id})
        return jsonify({'status': 'ok'}), 201
    except Exception as e:
        logger.error(f'add_inventory_template_location: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-templates/<int:template_id>/locations/<location_id>', methods=['DELETE'])
@admin_required
def remove_inventory_template_location(template_id, location_id):
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM inventory_template_locations
                WHERE template_id = :template_id AND location_id = :location_id
            """), {'template_id': template_id, 'location_id': location_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'remove_inventory_template_location: {e}')
        return jsonify({'error': str(e)}), 500


# ── Template sections ──────────────────────────────────────────────────────────

@bp.route('/inventory-sections', methods=['POST'])
@admin_required
def create_inventory_section():
    data        = request.get_json(force=True)
    template_id = data.get('template_id')
    name        = (data.get('name') or '').strip()
    if not template_id or not name:
        return jsonify({'error': 'template_id and name are required'}), 400
    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO inventory_template_sections (template_id, name, sort_order)
                VALUES (:template_id, :name, :sort_order)
                RETURNING id
            """), {
                'template_id': template_id,
                'name':        name,
                'sort_order':  data.get('sort_order', 0),
            })
            section_id = result.fetchone().id
        return jsonify({'id': section_id}), 201
    except Exception as e:
        logger.error(f'create_inventory_section: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-sections/<int:section_id>', methods=['PUT'])
@admin_required
def update_inventory_section(section_id):
    data = request.get_json(force=True)
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE inventory_template_sections
                SET name = COALESCE(:name, name), sort_order = COALESCE(:sort_order, sort_order)
                WHERE id = :id
            """), {'id': section_id, 'name': data.get('name'), 'sort_order': data.get('sort_order')})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'update_inventory_section: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-sections/<int:section_id>', methods=['DELETE'])
@admin_required
def delete_inventory_section(section_id):
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""DELETE FROM inventory_template_sections WHERE id = :id"""), {'id': section_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_inventory_section: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-sections/<int:section_id>/items', methods=['POST'])
@admin_required
def add_inventory_section_item(section_id):
    data       = request.get_json(force=True)
    product_id = data.get('product_id')
    if not product_id:
        return jsonify({'error': 'product_id is required'}), 400
    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO inventory_template_items (section_id, product_id, sort_order)
                VALUES (:section_id, :product_id, :sort_order)
                ON CONFLICT (section_id, product_id) DO NOTHING
                RETURNING id
            """), {
                'section_id': section_id,
                'product_id': product_id,
                'sort_order': data.get('sort_order', 0),
            })
            row = result.fetchone()
        return jsonify({'id': row.id if row else None}), 201
    except Exception as e:
        logger.error(f'add_inventory_section_item: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-template-items/<int:item_id>', methods=['DELETE'])
@admin_required
def delete_inventory_section_item(item_id):
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""DELETE FROM inventory_template_items WHERE id = :id"""), {'id': item_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_inventory_section_item: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Inventory Template Item Units
# =============================================================================

@bp.route('/inventory-template-items/<int:item_id>/units', methods=['POST'])
@admin_required
def add_inventory_item_unit(item_id):
    data    = request.get_json(force=True)
    unit_id = data.get('unit_id')
    if not unit_id:
        return jsonify({'error': 'unit_id is required'}), 400
    try:
        with get_engine().begin() as conn:
            item = conn.execute(text("""
                SELECT product_id FROM inventory_template_items WHERE id = :id
            """), {'id': item_id}).fetchone()
            if not item:
                return jsonify({'error': 'Template item not found'}), 404
            if not has_base_conversion(conn, item.product_id, int(unit_id)):
                return jsonify({'error': 'This unit has no conversion to the product\'s base unit. '
                                         'Add the conversion on the product first.'}), 400
            result = conn.execute(text("""
                INSERT INTO inventory_template_item_units (item_id, unit_id, sort_order)
                VALUES (:item_id, :unit_id, :sort_order)
                ON CONFLICT (item_id, unit_id) DO NOTHING
                RETURNING id
            """), {
                'item_id':    item_id,
                'unit_id':    unit_id,
                'sort_order': data.get('sort_order', 0),
            })
            row = result.fetchone()
        return jsonify({'id': row.id if row else None}), 201
    except Exception as e:
        logger.error(f'add_inventory_item_unit: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-template-item-units/<int:unit_id>', methods=['DELETE'])
@admin_required
def remove_inventory_item_unit(unit_id):
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM inventory_template_item_units WHERE id = :id
            """), {'id': unit_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'remove_inventory_item_unit: {e}')
        return jsonify({'error': str(e)}), 500
