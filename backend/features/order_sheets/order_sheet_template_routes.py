# =============================================================================
# backend/features/order_sheets/order_sheet_template_routes.py
# =============================================================================
# Order Templates (admin): the templates stores count from. Templates, sections, products, count units, and which locations use them.
#
# Endpoints in this file:
#   GET     /api/sheet-templates                                            list_sheet_templates
#   POST    /api/sheet-templates                                            create_sheet_template
#   POST    /api/sheet-templates/<int:template_id>/sort                     sort_sheet_template
#   GET     /api/sheet-templates/<int:template_id>                          get_sheet_template
#   POST    /api/sheet-templates/<int:template_id>/duplicate                duplicate_sheet_template
#   POST    /api/sheet-templates/<int:template_id>/toggle-active            toggle_template_active
#   PUT     /api/sheet-templates/<int:template_id>                          update_sheet_template
#   POST    /api/sheet-templates/<int:template_id>/locations                assign_template_location
#   DELETE  /api/sheet-templates/<int:template_id>/locations/<location_id>  unassign_template_location
#   POST    /api/sheet-sections                                             create_sheet_section
#   PUT     /api/sheet-sections/<int:section_id>                            update_sheet_section
#   DELETE  /api/sheet-sections/<int:section_id>                            delete_sheet_section
#   POST    /api/sheet-sections/<int:section_id>/items                      add_section_item
#   POST    /api/sheet-section-items/<int:item_id>/units                    add_section_item_unit
#   DELETE  /api/sheet-section-item-units/<int:unit_id>                     remove_section_item_unit
#   DELETE  /api/sheet-section-items/<int:item_id>                          remove_section_item
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
import logging

from core.auth import (
    admin_required, staff_required, _get_user_location,
)
from core.database import get_engine
from core.units import has_base_conversion

logger = logging.getLogger(__name__)

bp = Blueprint('order_sheet_template_routes', __name__, url_prefix='/api')


@bp.route('/sheet-templates', methods=['GET'])
@staff_required
def list_sheet_templates():
    """
    List sheet templates.
    Admin sees all. Staff sees only templates assigned to their location.
    """
    roles        = g.user.get('roles', [])
    is_admin     = 'admin' in roles
    location_id  = request.args.get('location_id')
    show_inactive = request.args.get('show_inactive', 'false').lower() == 'true'
    active_filter = '' if (is_admin and show_inactive) else 'WHERE st.active = TRUE'

    with get_engine().connect() as conn:
        if is_admin and not location_id:
            rows = conn.execute(text(f"""
                SELECT
                    st.id, st.name, st.notes, st.active,
                    st.created_by, st.created_at,
                    COUNT(DISTINCT stl.location_id) AS location_count,
                    COUNT(DISTINCT ss.id)            AS section_count
                FROM sheet_templates st
                LEFT JOIN sheet_template_locations stl ON stl.template_id = st.id
                LEFT JOIN sheet_sections ss            ON ss.template_id  = st.id
                {active_filter}
                GROUP BY st.id
                ORDER BY st.name
            """)).mappings().all()
        else:
            if not location_id and not is_admin:
                with get_engine().connect() as c2:
                    location_id = _get_user_location(c2)

            rows = conn.execute(text("""
                SELECT
                    st.id, st.name, st.notes, st.active,
                    st.created_by, st.created_at,
                    COUNT(DISTINCT ss.id) AS section_count
                FROM sheet_templates st
                JOIN sheet_template_locations stl ON stl.template_id = st.id
                LEFT JOIN sheet_sections ss        ON ss.template_id  = st.id
                WHERE st.active = TRUE
                AND stl.location_id = :location_id
                GROUP BY st.id
                ORDER BY st.name
            """), {'location_id': location_id}).mappings().all()

    return jsonify([dict(r) for r in rows])


@bp.route('/sheet-templates', methods=['POST'])
@admin_required
def create_sheet_template():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400

    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO sheet_templates (name, notes, created_by)
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
        if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
            return jsonify({'error': f'A template named "{name}" already exists.'}), 409
        logger.error(f'create_sheet_template: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Sheet Templates — detail / update
# =============================================================================

@bp.route('/sheet-templates/<int:template_id>/sort', methods=['POST'])
@admin_required
def sort_sheet_template(template_id):
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
                    UPDATE sheet_sections
                    SET sort_order = :sort_order
                    WHERE id = :id
                """), {'id': section['id'], 'sort_order': section['sort_order']})

                for item in section.get('items', []):
                    conn.execute(text("""
                        UPDATE sheet_section_items
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
        logger.error(f'sort_sheet_template: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-templates/<int:template_id>', methods=['GET'])
@staff_required
def get_sheet_template(template_id):
    """Full template detail with sections, items, and assigned locations."""
    with get_engine().connect() as conn:
        template = conn.execute(text("""
            SELECT id, name, notes, active, is_commissary, created_by, created_at, updated_at
            FROM sheet_templates WHERE id = :id
        """), {'id': template_id}).mappings().fetchone()

        if not template:
            return jsonify({'error': 'Template not found'}), 404

        # Sections with their items
        sections = conn.execute(text("""
            SELECT
                ss.id, ss.name, ss.sort_order,
                json_agg(
                    json_build_object(
                        'id',           ssi.id,
                        'product_id',   ssi.product_id,
                        'product_name', p.name,
                        'category',     c.name,
                        'base_unit',    u.name,
                        'base_unit_id', p.base_unit_id,
                        'sort_order',   ssi.sort_order
                    ) ORDER BY ssi.sort_order
                ) FILTER (WHERE ssi.id IS NOT NULL) AS items
            FROM sheet_sections ss
            LEFT JOIN sheet_section_items ssi ON ssi.section_id = ss.id
            LEFT JOIN products p              ON ssi.product_id = p.id
            LEFT JOIN product_categories c    ON p.category_id  = c.id
            LEFT JOIN units u                 ON p.base_unit_id = u.id
            WHERE ss.template_id = :id
            GROUP BY ss.id
            ORDER BY ss.sort_order
        """), {'id': template_id}).mappings().all()

        # Assigned locations
        locations = conn.execute(text("""
            SELECT stl.location_id, l.location_name
            FROM sheet_template_locations stl
            JOIN locations l ON l.store_guid::text = stl.location_id
            WHERE stl.template_id = :id
            ORDER BY l.location_name
        """), {'id': template_id}).mappings().all()

        # Count units per section item
        count_units = conn.execute(text("""
            SELECT
                ssiu.id,
                ssiu.item_id,
                ssiu.unit_id,
                ssiu.sort_order,
                u.name    AS unit_name,
                u.display AS unit_display
            FROM sheet_section_item_units ssiu
            JOIN units u ON ssiu.unit_id = u.id
            JOIN sheet_section_items ssi ON ssiu.item_id = ssi.id
            JOIN sheet_sections ss ON ssi.section_id = ss.id
            WHERE ss.template_id = :id
            ORDER BY ssiu.item_id, ssiu.sort_order
        """), {'id': template_id}).mappings().all()

    # Build count units map: item_id → [units]
    count_units_map = {}
    for cu in count_units:
        iid = cu['item_id']
        if iid not in count_units_map:
            count_units_map[iid] = []
        count_units_map[iid].append(dict(cu))

    result = dict(template)
    result['sections']  = [dict(s) for s in sections]
    result['locations'] = [dict(l) for l in locations]

    # Merge count units into section items
    for section in result['sections']:
        if section.get('items'):
            for item in section['items']:
                item['count_units'] = count_units_map.get(item['id'], [])

    return jsonify(result)


@bp.route('/sheet-templates/<int:template_id>/duplicate', methods=['POST'])
@admin_required
def duplicate_sheet_template(template_id):
    """Duplicate a sheet template with all sections, items and count units."""
    try:
        with get_engine().begin() as conn:
            # Get source template
            source = conn.execute(text("""
                SELECT name, notes, is_commissary FROM sheet_templates WHERE id = :id
            """), {'id': template_id}).fetchone()

            if not source:
                return jsonify({'error': 'Template not found'}), 404

            # Create new template
            new_tmpl = conn.execute(text("""
                INSERT INTO sheet_templates (name, notes, is_commissary, active, created_by)
                VALUES (:name, :notes, :is_commissary, TRUE, :created_by)
                RETURNING id
            """), {
                'name':          f'Copy of {source.name}',
                'notes':         source.notes,
                'is_commissary': source.is_commissary,
                'created_by':    g.user.get('email'),
            }).fetchone().id

            # Get source sections
            sections = conn.execute(text("""
                SELECT id, name, sort_order FROM sheet_sections
                WHERE template_id = :id ORDER BY sort_order
            """), {'id': template_id}).fetchall()

            for section in sections:
                # Create new section
                new_section = conn.execute(text("""
                    INSERT INTO sheet_sections (template_id, name, sort_order)
                    VALUES (:template_id, :name, :sort_order)
                    RETURNING id
                """), {
                    'template_id': new_tmpl,
                    'name':        section.name,
                    'sort_order':  section.sort_order,
                }).fetchone().id

                # Get source items
                items = conn.execute(text("""
                    SELECT id, product_id, sort_order FROM sheet_section_items
                    WHERE section_id = :id ORDER BY sort_order
                """), {'id': section.id}).fetchall()

                for item in items:
                    # Create new item
                    new_item = conn.execute(text("""
                        INSERT INTO sheet_section_items (section_id, product_id, sort_order)
                        VALUES (:section_id, :product_id, :sort_order)
                        RETURNING id
                    """), {
                        'section_id': new_section,
                        'product_id': item.product_id,
                        'sort_order': item.sort_order,
                    }).fetchone().id

                    # Copy count units
                    units = conn.execute(text("""
                        SELECT unit_id, sort_order FROM sheet_section_item_units
                        WHERE item_id = :id ORDER BY sort_order
                    """), {'id': item.id}).fetchall()

                    for unit in units:
                        conn.execute(text("""
                            INSERT INTO sheet_section_item_units (item_id, unit_id, sort_order)
                            VALUES (:item_id, :unit_id, :sort_order)
                        """), {
                            'item_id':    new_item,
                            'unit_id':    unit.unit_id,
                            'sort_order': unit.sort_order,
                        })

            # Copy location assignments
            conn.execute(text("""
                INSERT INTO sheet_template_locations (template_id, location_id)
                SELECT :new_id, location_id FROM sheet_template_locations
                WHERE template_id = :old_id
            """), {'new_id': new_tmpl, 'old_id': template_id})

        return jsonify({'id': new_tmpl}), 201
    except Exception as e:
        if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
            return jsonify({'error': 'A template with that name already exists. Rename the original first.'}), 409
        logger.error(f'duplicate_sheet_template: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-templates/<int:template_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_template_active(template_id):
    """Toggle a sheet template active/inactive."""
    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                UPDATE sheet_templates SET
                    active     = NOT active,
                    updated_at = NOW()
                WHERE id = :id
                RETURNING active
            """), {'id': template_id})
            new_active = result.fetchone().active
        return jsonify({'status': 'ok', 'active': new_active})
    except Exception as e:
        logger.error(f'toggle_template_active: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-templates/<int:template_id>', methods=['PUT'])
@admin_required
def update_sheet_template(template_id):
    data = request.get_json(force=True)
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE sheet_templates SET
                    name          = COALESCE(:name, name),
                    notes         = :notes,
                    active        = COALESCE(:active, active),
                    is_commissary = COALESCE(:is_commissary, is_commissary),
                    updated_at    = NOW()
                WHERE id = :id
            """), {
                'id':            template_id,
                'name':          data.get('name'),
                'notes':         data.get('notes'),
                'active':        data.get('active'),
                'is_commissary': data.get('is_commissary'),
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
            return jsonify({'error': f'A template with that name already exists.'}), 409
        logger.error(f'update_sheet_template: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Template location assignment
# =============================================================================

@bp.route('/sheet-templates/<int:template_id>/locations', methods=['POST'])
@admin_required
def assign_template_location(template_id):
    data        = request.get_json(force=True)
    location_id = data.get('location_id')
    if not location_id:
        return jsonify({'error': 'location_id is required'}), 400

    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO sheet_template_locations (template_id, location_id)
                VALUES (:template_id, :location_id)
                ON CONFLICT DO NOTHING
            """), {'template_id': template_id, 'location_id': location_id})
        return jsonify({'status': 'ok'}), 201
    except Exception as e:
        logger.error(f'assign_template_location: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-templates/<int:template_id>/locations/<location_id>', methods=['DELETE'])
@admin_required
def unassign_template_location(template_id, location_id):
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM sheet_template_locations
                WHERE template_id = :template_id
                AND location_id   = :location_id
            """), {'template_id': template_id, 'location_id': location_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'unassign_template_location: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Sheet Sections
# =============================================================================

@bp.route('/sheet-sections', methods=['POST'])
@admin_required
def create_sheet_section():
    data        = request.get_json(force=True)
    template_id = data.get('template_id')
    name        = (data.get('name') or '').strip()

    if not template_id:
        return jsonify({'error': 'template_id is required'}), 400
    if not name:
        return jsonify({'error': 'name is required'}), 400

    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO sheet_sections (template_id, name, sort_order)
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
        logger.error(f'create_sheet_section: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-sections/<int:section_id>', methods=['PUT'])
@admin_required
def update_sheet_section(section_id):
    data = request.get_json(force=True)
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE sheet_sections SET
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
        logger.error(f'update_sheet_section: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-sections/<int:section_id>', methods=['DELETE'])
@admin_required
def delete_sheet_section(section_id):
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM sheet_sections WHERE id = :id
            """), {'id': section_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_sheet_section: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Sheet Section Items
# =============================================================================

@bp.route('/sheet-sections/<int:section_id>/items', methods=['POST'])
@admin_required
def add_section_item(section_id):
    data       = request.get_json(force=True)
    product_id = data.get('product_id')

    if not product_id:
        return jsonify({'error': 'product_id is required'}), 400

    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO sheet_section_items (section_id, product_id, sort_order)
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
        logger.error(f'add_section_item: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-section-items/<int:item_id>/units', methods=['POST'])
@admin_required
def add_section_item_unit(item_id):
    """Add a count unit to a section item."""
    data    = request.get_json(force=True)
    unit_id = data.get('unit_id')

    if not unit_id:
        return jsonify({'error': 'unit_id is required'}), 400

    try:
        with get_engine().begin() as conn:
            item = conn.execute(text("""
                SELECT product_id FROM sheet_section_items WHERE id = :id
            """), {'id': item_id}).fetchone()
            if not item:
                return jsonify({'error': 'Template item not found'}), 404
            if not has_base_conversion(conn, item.product_id, int(unit_id)):
                return jsonify({'error': 'This unit has no conversion to the product\'s base unit. '
                                         'Add the conversion on the product first.'}), 400
            result = conn.execute(text("""
                INSERT INTO sheet_section_item_units (item_id, unit_id, sort_order)
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
        logger.error(f'add_section_item_unit: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-section-item-units/<int:unit_id>', methods=['DELETE'])
@admin_required
def remove_section_item_unit(unit_id):
    """Remove a count unit from a section item."""
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM sheet_section_item_units WHERE id = :id
            """), {'id': unit_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'remove_section_item_unit: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-section-items/<int:item_id>', methods=['DELETE'])
@admin_required
def remove_section_item(item_id):
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM sheet_section_items WHERE id = :id
            """), {'id': item_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'remove_section_item: {e}')
        return jsonify({'error': str(e)}), 500
