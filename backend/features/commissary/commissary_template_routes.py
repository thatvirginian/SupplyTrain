# =============================================================================
# backend/features/commissary/commissary_template_routes.py
# =============================================================================
# Comm Templates (admin / commissary GM): templates for commissary orders, by location and vendor.
#
# Endpoints in this file:
#   GET     /api/comm-order-templates                                  list_comm_order_templates
#   POST    /api/comm-order-templates                                  create_comm_order_template
#   GET     /api/comm-order-templates/<int:template_id>                get_comm_order_template
#   PUT     /api/comm-order-templates/<int:template_id>                update_comm_order_template
#   POST    /api/comm-order-templates/<int:template_id>/toggle-active  toggle_comm_order_template
#   POST    /api/comm-order-templates/<int:template_id>/sort           sort_comm_order_template
#   POST    /api/comm-order-sections                                   create_comm_order_section
#   PUT     /api/comm-order-sections/<int:section_id>                  update_comm_order_section
#   DELETE  /api/comm-order-sections/<int:section_id>                  delete_comm_order_section
#   POST    /api/comm-order-sections/<int:section_id>/items            add_comm_order_section_item
#   DELETE  /api/comm-order-template-items/<int:item_id>               delete_comm_order_section_item
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
import logging

from core.auth import (
    admin_required, comm_manage_required,
)
from core.database import get_engine

logger = logging.getLogger(__name__)

bp = Blueprint('commissary_template_routes', __name__, url_prefix='/api')


# =============================================================================
# Commissary Order Templates
# =============================================================================

@bp.route('/comm-order-templates', methods=['GET'])
@comm_manage_required
def list_comm_order_templates():
    """List commissary order templates, optionally filtered by location(s)."""
    location_ids = request.args.getlist('location_id')

    with get_engine().connect() as conn:
        where = ''
        params = {}
        if location_ids:
            where = 'WHERE ct.location_id = ANY(:location_ids)'
            params['location_ids'] = location_ids

        rows = conn.execute(text(f"""
            SELECT
                ct.id, ct.location_id, ct.vendor_id, ct.name, ct.notes, ct.active,
                ct.created_at, ct.updated_at,
                l.location_name,
                v.name AS vendor_name,
                COUNT(DISTINCT cts.id) AS section_count,
                COUNT(DISTINCT cti.id) AS item_count
            FROM comm_order_templates ct
            LEFT JOIN locations l                      ON l.store_guid::text = ct.location_id
            LEFT JOIN vendors v                        ON ct.vendor_id       = v.id
            LEFT JOIN comm_order_template_sections cts ON cts.template_id   = ct.id
            LEFT JOIN comm_order_template_items cti    ON cti.section_id    = cts.id
            {where}
            GROUP BY ct.id, l.location_name, v.name
            ORDER BY l.location_name, v.name
        """), params).mappings().all()
    return jsonify([dict(r) for r in rows])


@bp.route('/comm-order-templates', methods=['POST'])
@comm_manage_required
def create_comm_order_template():
    data        = request.get_json(force=True)
    location_id = data.get('location_id')
    vendor_id   = data.get('vendor_id')
    name        = (data.get('name') or '').strip()

    if not location_id:
        return jsonify({'error': 'location_id is required'}), 400
    if not vendor_id:
        return jsonify({'error': 'vendor_id is required'}), 400
    if not name:
        return jsonify({'error': 'name is required'}), 400

    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO comm_order_templates (location_id, vendor_id, name, notes, created_by)
                VALUES (:location_id, :vendor_id, :name, :notes, :created_by)
                ON CONFLICT (location_id, vendor_id) DO UPDATE SET
                    name       = EXCLUDED.name,
                    notes      = EXCLUDED.notes,
                    active     = TRUE,
                    updated_at = NOW()
                RETURNING id
            """), {
                'location_id': location_id,
                'vendor_id':   int(vendor_id),
                'name':        name,
                'notes':       data.get('notes'),
                'created_by':  g.user.get('email'),
            })
            template_id = result.fetchone().id
        return jsonify({'id': template_id}), 201
    except Exception as e:
        logger.error(f'create_comm_order_template: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/comm-order-templates/<int:template_id>', methods=['GET'])
@comm_manage_required
def get_comm_order_template(template_id):
    """Full commissary template detail with sections and items."""
    with get_engine().connect() as conn:
        template = conn.execute(text("""
            SELECT ct.id, ct.location_id, ct.vendor_id, ct.name, ct.notes, ct.active,
                   ct.created_at, ct.updated_at,
                   l.location_name,
                   v.name AS vendor_name
            FROM comm_order_templates ct
            LEFT JOIN locations l ON l.store_guid::text = ct.location_id
            LEFT JOIN vendors v   ON ct.vendor_id       = v.id
            WHERE ct.id = :id
        """), {'id': template_id}).mappings().fetchone()

        if not template:
            return jsonify({'error': 'Template not found'}), 404

        sections = conn.execute(text("""
            SELECT
                s.id, s.name, s.sort_order,
                json_agg(
                    json_build_object(
                        'id',           i.id,
                        'product_id',   i.product_id,
                        'product_name', p.name,
                        'category',     c.name,
                        'base_unit',    u.name,
                        'sort_order',   i.sort_order
                    ) ORDER BY i.sort_order
                ) FILTER (WHERE i.id IS NOT NULL) AS items
            FROM comm_order_template_sections s
            LEFT JOIN comm_order_template_items i ON i.section_id   = s.id
            LEFT JOIN products p                  ON i.product_id   = p.id
            LEFT JOIN product_categories c        ON p.category_id  = c.id
            LEFT JOIN units u                     ON p.base_unit_id = u.id
            WHERE s.template_id = :id
            GROUP BY s.id
            ORDER BY s.sort_order
        """), {'id': template_id}).mappings().all()

    result = dict(template)
    result['sections'] = [dict(s) for s in sections]
    return jsonify(result)


@bp.route('/comm-order-templates/<int:template_id>', methods=['PUT'])
@comm_manage_required
def update_comm_order_template(template_id):
    data = request.get_json(force=True)
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE comm_order_templates SET
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
        logger.error(f'update_comm_order_template: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/comm-order-templates/<int:template_id>/toggle-active', methods=['POST'])
@comm_manage_required
def toggle_comm_order_template(template_id):
    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                UPDATE comm_order_templates SET
                    active     = NOT active,
                    updated_at = NOW()
                WHERE id = :id
                RETURNING active
            """), {'id': template_id})
            new_active = result.fetchone().active
        return jsonify({'status': 'ok', 'active': new_active})
    except Exception as e:
        logger.error(f'toggle_comm_order_template: {e}')
        return jsonify({'error': str(e)}), 500


# ── Sections ──────────────────────────────────────────────────────────────────

@bp.route('/comm-order-templates/<int:template_id>/sort', methods=['POST'])
@comm_manage_required
def sort_comm_order_template(template_id):
    """
    Save section and item sort orders in one call.
    Also updates section_id when items have been moved between sections.
    Body: { sections: [{ id, sort_order, items: [{ id, sort_order }] }] }
    """
    data     = request.get_json(force=True)
    sections = data.get('sections', [])
    try:
        with get_engine().begin() as conn:
            for section in sections:
                conn.execute(text("""
                    UPDATE comm_order_template_sections
                    SET sort_order = :sort_order
                    WHERE id = :id
                """), {'id': section['id'], 'sort_order': section['sort_order']})

                for item in section.get('items', []):
                    conn.execute(text("""
                        UPDATE comm_order_template_items
                        SET sort_order = :sort_order,
                            section_id = :section_id
                        WHERE id = :id
                    """), {
                        'id':         item['id'],
                        'sort_order': item['sort_order'],
                        'section_id': section['id'],
                    })

        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'sort_comm_order_template: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/comm-order-sections', methods=['POST'])
@comm_manage_required
def create_comm_order_section():
    data        = request.get_json(force=True)
    template_id = data.get('template_id')
    name        = (data.get('name') or '').strip()

    if not template_id or not name:
        return jsonify({'error': 'template_id and name are required'}), 400

    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO comm_order_template_sections (template_id, name, sort_order)
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
        logger.error(f'create_comm_order_section: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/comm-order-sections/<int:section_id>', methods=['PUT'])
@comm_manage_required
def update_comm_order_section(section_id):
    data = request.get_json(force=True)
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE comm_order_template_sections SET
                    name       = COALESCE(:name, name),
                    sort_order = COALESCE(:sort_order, sort_order)
                WHERE id = :id
            """), {
                'id':         section_id,
                'name':       data.get('name'),
                'sort_order': data.get('sort_order'),
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'update_comm_order_section: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/comm-order-sections/<int:section_id>', methods=['DELETE'])
@admin_required
def delete_comm_order_section(section_id):
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM comm_order_template_sections WHERE id = :id
            """), {'id': section_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_comm_order_section: {e}')
        return jsonify({'error': str(e)}), 500


# ── Section items ─────────────────────────────────────────────────────────────

@bp.route('/comm-order-sections/<int:section_id>/items', methods=['POST'])
@admin_required
def add_comm_order_section_item(section_id):
    data       = request.get_json(force=True)
    product_id = data.get('product_id')
    if not product_id:
        return jsonify({'error': 'product_id is required'}), 400

    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO comm_order_template_items (section_id, product_id, sort_order)
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
        logger.error(f'add_comm_order_section_item: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/comm-order-template-items/<int:item_id>', methods=['DELETE'])
@admin_required
def delete_comm_order_section_item(item_id):
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM comm_order_template_items WHERE id = :id
            """), {'id': item_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_comm_order_section_item: {e}')
        return jsonify({'error': str(e)}), 500
