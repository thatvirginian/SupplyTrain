# =============================================================================
# backend/features/commissary/production_template_routes.py
# =============================================================================
# Production Templates (admin, commissary GM): the sheets the commissary fills
# in to record what it made. Template -> sections -> products, each product
# with ONE production unit (default: its base unit). Assigned to commissaries.
#
# A product's unit must convert to its base unit (same rule as inventory
# count units): the run stores the amount as entered AND in base units.
#
# Endpoints in this file:
#   GET     /api/production-templates                                            list_production_templates
#   POST    /api/production-templates                                            create_production_template
#   GET     /api/production-templates/<int:template_id>                          get_production_template
#   PUT     /api/production-templates/<int:template_id>                          update_production_template
#   POST    /api/production-templates/<int:template_id>/toggle-active            toggle_production_template
#   POST    /api/production-templates/<int:template_id>/duplicate                duplicate_production_template
#   POST    /api/production-templates/<int:template_id>/sort                     sort_production_template
#   POST    /api/production-templates/<int:template_id>/locations                add_production_template_location
#   DELETE  /api/production-templates/<int:template_id>/locations/<location_id>  remove_production_template_location
#   POST    /api/production-sections                                             create_production_section
#   PUT     /api/production-sections/<int:section_id>                            update_production_section
#   DELETE  /api/production-sections/<int:section_id>                            delete_production_section
#   POST    /api/production-sections/<int:section_id>/items                      add_production_item
#   PUT     /api/production-template-items/<int:item_id>                         update_production_item
#   DELETE  /api/production-template-items/<int:item_id>                         delete_production_item
#   GET     /api/production-products                                             search_production_products
#   GET     /api/production-products/<int:product_id>/units                      production_product_units
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
import logging

from core.auth import comm_required, production_template_required, _is_admin
from core.database import get_engine
from core.units import has_base_conversion, load_unit_choices
from features.commissary.commissary_access import (
    CommissaryAccessError, is_commissary_location, resolve_commissary_location,
)

logger = logging.getLogger(__name__)

bp = Blueprint('production_template_routes', __name__, url_prefix='/api')


def _err(e):
    if isinstance(e, CommissaryAccessError):
        return jsonify({'error': str(e)}), e.status
    raise e


# =============================================================================
# Templates
# =============================================================================

@bp.route('/production-templates', methods=['GET'])
@comm_required
def list_production_templates():
    """
    Template editors (admin, commissary GM) without location_id: every template
    (show_inactive=true includes inactive ones).
    With location_id, or commissary staff: the active templates assigned to
    that commissary (staff: their own).
    """
    location_id   = request.args.get('location_id')
    show_inactive = request.args.get('show_inactive', 'false').lower() == 'true'
    roles         = g.user.get('roles', [])
    is_editor     = 'admin' in roles or 'commissary_gm' in roles

    try:
        with get_engine().connect() as conn:
            if is_editor and not location_id:
                active_filter = '' if show_inactive else 'WHERE pt.active = TRUE'
                rows = conn.execute(text(f"""
                    SELECT pt.id, pt.name, pt.notes, pt.active, pt.created_at, pt.updated_at,
                           COUNT(DISTINCT ptl.location_id) AS location_count,
                           COUNT(DISTINCT pts.id)           AS section_count,
                           COUNT(DISTINCT pti.id)           AS item_count
                    FROM production_templates pt
                    LEFT JOIN production_template_locations ptl ON ptl.template_id = pt.id
                    LEFT JOIN production_template_sections  pts ON pts.template_id = pt.id
                    LEFT JOIN production_template_items     pti ON pti.section_id  = pts.id
                    {active_filter}
                    GROUP BY pt.id
                    ORDER BY pt.name
                """)).mappings().all()
            else:
                location_id = resolve_commissary_location(conn, location_id)
                rows = conn.execute(text("""
                    SELECT pt.id, pt.name, pt.notes, pt.active, pt.created_at, pt.updated_at,
                           COUNT(DISTINCT pts.id) AS section_count,
                           COUNT(DISTINCT pti.id) AS item_count
                    FROM production_templates pt
                    JOIN production_template_locations ptl ON ptl.template_id = pt.id
                    LEFT JOIN production_template_sections pts ON pts.template_id = pt.id
                    LEFT JOIN production_template_items    pti ON pti.section_id  = pts.id
                    WHERE pt.active = TRUE AND ptl.location_id = :location_id
                    GROUP BY pt.id
                    ORDER BY pt.name
                """), {'location_id': location_id}).mappings().all()
        return jsonify([dict(r) for r in rows])
    except CommissaryAccessError as e:
        return _err(e)


@bp.route('/production-templates', methods=['POST'])
@production_template_required
def create_production_template():
    data = request.get_json(force=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    try:
        with get_engine().begin() as conn:
            row = conn.execute(text("""
                INSERT INTO production_templates (name, notes, created_by)
                VALUES (:name, :notes, :created_by)
                RETURNING id
            """), {'name': name, 'notes': data.get('notes'),
                   'created_by': g.user.get('email')}).fetchone()
        return jsonify({'id': row.id}), 201
    except Exception as e:
        logger.error(f'create_production_template: {e}')
        return jsonify({'error': str(e)}), 500


def load_production_template(conn, template_id):
    """Template with its sections, items (with unit names) and locations. None when missing."""
    template = conn.execute(text("""
        SELECT id, name, notes, active, created_at, updated_at
        FROM production_templates WHERE id = :id
    """), {'id': template_id}).mappings().fetchone()
    if not template:
        return None

    sections = conn.execute(text("""
        SELECT pts.id, pts.name, pts.sort_order,
               json_agg(
                   json_build_object(
                       'id',           pti.id,
                       'product_id',   pti.product_id,
                       'product_name', p.name,
                       'category',     c.name,
                       'unit_id',      pti.unit_id,
                       'unit_name',    u.name,
                       'base_unit_id', p.base_unit_id,
                       'base_unit',    bu.name,
                       'sort_order',   pti.sort_order
                   ) ORDER BY pti.sort_order, pti.id
               ) FILTER (WHERE pti.id IS NOT NULL) AS items
        FROM production_template_sections pts
        LEFT JOIN production_template_items pti ON pti.section_id = pts.id
        LEFT JOIN products p            ON p.id  = pti.product_id
        LEFT JOIN product_categories c  ON c.id  = p.category_id
        LEFT JOIN units u               ON u.id  = pti.unit_id
        LEFT JOIN units bu              ON bu.id = p.base_unit_id
        WHERE pts.template_id = :id
        GROUP BY pts.id
        ORDER BY pts.sort_order, pts.id
    """), {'id': template_id}).mappings().all()

    locations = conn.execute(text("""
        SELECT ptl.location_id, l.location_name
        FROM production_template_locations ptl
        LEFT JOIN locations l ON l.store_guid::text = ptl.location_id
        WHERE ptl.template_id = :id
        ORDER BY l.location_name
    """), {'id': template_id}).mappings().all()

    result = dict(template)
    result['sections']  = [dict(s, items=s['items'] or []) for s in sections]
    result['locations'] = [dict(l) for l in locations]
    return result


@bp.route('/production-templates/<int:template_id>', methods=['GET'])
@comm_required
def get_production_template(template_id):
    with get_engine().connect() as conn:
        result = load_production_template(conn, template_id)
    if not result:
        return jsonify({'error': 'Template not found'}), 404
    return jsonify(result)


@bp.route('/production-templates/<int:template_id>', methods=['PUT'])
@production_template_required
def update_production_template(template_id):
    data = request.get_json(force=True) or {}
    name = data.get('name')
    if name is not None and not name.strip():
        return jsonify({'error': 'name cannot be empty'}), 400
    with get_engine().begin() as conn:
        row = conn.execute(text("""
            UPDATE production_templates SET
                name       = COALESCE(:name, name),
                notes      = :notes,
                updated_at = NOW()
            WHERE id = :id
            RETURNING id
        """), {'id': template_id, 'name': name.strip() if name else None,
               'notes': data.get('notes')}).fetchone()
    if not row:
        return jsonify({'error': 'Template not found'}), 404
    return jsonify({'status': 'ok'})


@bp.route('/production-templates/<int:template_id>/toggle-active', methods=['POST'])
@production_template_required
def toggle_production_template(template_id):
    with get_engine().begin() as conn:
        row = conn.execute(text("""
            UPDATE production_templates SET active = NOT active, updated_at = NOW()
            WHERE id = :id RETURNING active
        """), {'id': template_id}).fetchone()
    if not row:
        return jsonify({'error': 'Template not found'}), 404
    return jsonify({'status': 'ok', 'active': row.active})


@bp.route('/production-templates/<int:template_id>/duplicate', methods=['POST'])
@production_template_required
def duplicate_production_template(template_id):
    """Copy sections and items (with their units). Locations are not copied."""
    data = request.get_json(silent=True) or {}
    with get_engine().begin() as conn:
        src = conn.execute(text("""
            SELECT name, notes FROM production_templates WHERE id = :id
        """), {'id': template_id}).fetchone()
        if not src:
            return jsonify({'error': 'Template not found'}), 404
        new_id = conn.execute(text("""
            INSERT INTO production_templates (name, notes, created_by)
            VALUES (:name, :notes, :by) RETURNING id
        """), {'name': (data.get('name') or '').strip() or f'{src.name} (copy)',
               'notes': src.notes, 'by': g.user.get('email')}).fetchone().id
        sections = conn.execute(text("""
            SELECT id, name, sort_order FROM production_template_sections
            WHERE template_id = :id ORDER BY sort_order, id
        """), {'id': template_id}).fetchall()
        for s in sections:
            new_sid = conn.execute(text("""
                INSERT INTO production_template_sections (template_id, name, sort_order)
                VALUES (:tid, :name, :so) RETURNING id
            """), {'tid': new_id, 'name': s.name, 'so': s.sort_order}).fetchone().id
            conn.execute(text("""
                INSERT INTO production_template_items (section_id, product_id, unit_id, sort_order)
                SELECT :new_sid, product_id, unit_id, sort_order
                FROM production_template_items WHERE section_id = :sid
            """), {'new_sid': new_sid, 'sid': s.id})
    return jsonify({'id': new_id}), 201


@bp.route('/production-templates/<int:template_id>/sort', methods=['POST'])
@production_template_required
def sort_production_template(template_id):
    """Save section order and item order (items may move between this template's sections)."""
    data     = request.get_json(force=True) or {}
    sections = data.get('sections', [])
    with get_engine().begin() as conn:
        own = {r.id for r in conn.execute(text("""
            SELECT id FROM production_template_sections WHERE template_id = :id
        """), {'id': template_id}).fetchall()}
        for s in sections:
            if s.get('id') not in own:
                return jsonify({'error': 'A section does not belong to this template'}), 400
        for s in sections:
            conn.execute(text("""
                UPDATE production_template_sections SET sort_order = :so WHERE id = :id
            """), {'id': s['id'], 'so': s.get('sort_order', 0)})
            for item in s.get('items', []):
                conn.execute(text("""
                    UPDATE production_template_items
                    SET sort_order = :so, section_id = :sid
                    WHERE id = :id AND section_id = ANY(:own)
                """), {'id': item['id'], 'so': item.get('sort_order', 0),
                       'sid': s['id'], 'own': list(own)})
    return jsonify({'status': 'ok'})


@bp.route('/production-templates/<int:template_id>/locations', methods=['POST'])
@production_template_required
def add_production_template_location(template_id):
    """Assign to a commissary. Commissary GMs may only assign their own commissary."""
    data        = request.get_json(force=True) or {}
    location_id = data.get('location_id')
    if not location_id:
        return jsonify({'error': 'location_id is required'}), 400
    try:
        with get_engine().begin() as conn:
            if _is_admin():
                if not is_commissary_location(conn, location_id):
                    return jsonify({'error': 'Production templates can only be assigned to a commissary'}), 400
            else:
                resolve_commissary_location(conn, location_id)
            if not conn.execute(text("SELECT 1 FROM production_templates WHERE id = :id"),
                                {'id': template_id}).fetchone():
                return jsonify({'error': 'Template not found'}), 404
            conn.execute(text("""
                INSERT INTO production_template_locations (template_id, location_id)
                VALUES (:tid, :lid) ON CONFLICT DO NOTHING
            """), {'tid': template_id, 'lid': str(location_id)})
        return jsonify({'status': 'ok'}), 201
    except CommissaryAccessError as e:
        return _err(e)


@bp.route('/production-templates/<int:template_id>/locations/<location_id>', methods=['DELETE'])
@production_template_required
def remove_production_template_location(template_id, location_id):
    try:
        with get_engine().begin() as conn:
            if not _is_admin():
                resolve_commissary_location(conn, location_id)
            conn.execute(text("""
                DELETE FROM production_template_locations
                WHERE template_id = :tid AND location_id = :lid
            """), {'tid': template_id, 'lid': location_id})
        return jsonify({'status': 'ok'})
    except CommissaryAccessError as e:
        return _err(e)


# =============================================================================
# Sections
# =============================================================================

@bp.route('/production-sections', methods=['POST'])
@production_template_required
def create_production_section():
    data        = request.get_json(force=True) or {}
    template_id = data.get('template_id')
    name        = (data.get('name') or '').strip()
    if not template_id or not name:
        return jsonify({'error': 'template_id and name are required'}), 400
    with get_engine().begin() as conn:
        if not conn.execute(text("SELECT 1 FROM production_templates WHERE id = :id"),
                            {'id': template_id}).fetchone():
            return jsonify({'error': 'Template not found'}), 404
        row = conn.execute(text("""
            INSERT INTO production_template_sections (template_id, name, sort_order)
            VALUES (:tid, :name, :so) RETURNING id
        """), {'tid': template_id, 'name': name, 'so': data.get('sort_order', 0)}).fetchone()
    return jsonify({'id': row.id}), 201


@bp.route('/production-sections/<int:section_id>', methods=['PUT'])
@production_template_required
def update_production_section(section_id):
    data = request.get_json(force=True) or {}
    name = data.get('name')
    if name is not None and not name.strip():
        return jsonify({'error': 'name cannot be empty'}), 400
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE production_template_sections
            SET name = COALESCE(:name, name), sort_order = COALESCE(:so, sort_order)
            WHERE id = :id
        """), {'id': section_id, 'name': name.strip() if name else None,
               'so': data.get('sort_order')})
    return jsonify({'status': 'ok'})


@bp.route('/production-sections/<int:section_id>', methods=['DELETE'])
@production_template_required
def delete_production_section(section_id):
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM production_template_sections WHERE id = :id"),
                     {'id': section_id})
    return jsonify({'status': 'ok'})


# =============================================================================
# Items (product + production unit)
# =============================================================================

def _unit_error(conn, product_id, unit_id):
    """None when the unit is fine for this product, else the message to show."""
    if not has_base_conversion(conn, product_id, unit_id):
        return ("This unit has no conversion to the product's base unit. "
                "Add the conversion on the product first.")
    return None


@bp.route('/production-sections/<int:section_id>/items', methods=['POST'])
@production_template_required
def add_production_item(section_id):
    """Add a product. unit_id is optional: the product's base unit when left out."""
    data       = request.get_json(force=True) or {}
    product_id = data.get('product_id')
    if not product_id:
        return jsonify({'error': 'product_id is required'}), 400
    product_id = int(product_id)
    with get_engine().begin() as conn:
        if not conn.execute(text("SELECT 1 FROM production_template_sections WHERE id = :id"),
                            {'id': section_id}).fetchone():
            return jsonify({'error': 'Section not found'}), 404
        product = conn.execute(text("""
            SELECT id, base_unit_id FROM products WHERE id = :id
        """), {'id': product_id}).fetchone()
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        unit_id = int(data['unit_id']) if data.get('unit_id') else product.base_unit_id
        msg = _unit_error(conn, product_id, unit_id)
        if msg:
            return jsonify({'error': msg}), 400
        row = conn.execute(text("""
            INSERT INTO production_template_items (section_id, product_id, unit_id, sort_order)
            VALUES (:sid, :pid, :uid, :so)
            ON CONFLICT (section_id, product_id) DO NOTHING
            RETURNING id
        """), {'sid': section_id, 'pid': product_id, 'uid': unit_id,
               'so': data.get('sort_order', 0)}).fetchone()
        if not row:
            return jsonify({'error': 'That product is already in this section'}), 409
        # Make room: items at or after the new position move down one.
        conn.execute(text("""
            UPDATE production_template_items SET sort_order = sort_order + 1
            WHERE section_id = :sid AND id <> :id AND sort_order >= :so
        """), {'sid': section_id, 'id': row.id, 'so': data.get('sort_order', 0)})
    return jsonify({'id': row.id}), 201


@bp.route('/production-template-items/<int:item_id>', methods=['PUT'])
@production_template_required
def update_production_item(item_id):
    """Change a product's production unit. Runs already entered keep their own unit."""
    data    = request.get_json(force=True) or {}
    unit_id = data.get('unit_id')
    if not unit_id:
        return jsonify({'error': 'unit_id is required'}), 400
    with get_engine().begin() as conn:
        item = conn.execute(text("""
            SELECT product_id FROM production_template_items WHERE id = :id
        """), {'id': item_id}).fetchone()
        if not item:
            return jsonify({'error': 'Template item not found'}), 404
        msg = _unit_error(conn, item.product_id, int(unit_id))
        if msg:
            return jsonify({'error': msg}), 400
        conn.execute(text("""
            UPDATE production_template_items SET unit_id = :uid WHERE id = :id
        """), {'id': item_id, 'uid': int(unit_id)})
    return jsonify({'status': 'ok'})


@bp.route('/production-template-items/<int:item_id>', methods=['DELETE'])
@production_template_required
def delete_production_item(item_id):
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM production_template_items WHERE id = :id"), {'id': item_id})
    return jsonify({'status': 'ok'})


# =============================================================================
# Product search and unit choices for the template editor
# (/api/products is admin only; commissary GMs build templates too)
# =============================================================================

@bp.route('/production-products', methods=['GET'])
@production_template_required
def search_production_products():
    search = (request.args.get('search') or '').strip()
    limit  = min(int(request.args.get('per_page', 10) or 10), 50)
    if len(search) < 2:
        return jsonify({'products': []})
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT p.id, p.name, c.name AS category_name, u.name AS base_unit, p.base_unit_id
            FROM products p
            LEFT JOIN product_categories c ON c.id = p.category_id
            LEFT JOIN units u              ON u.id = p.base_unit_id
            WHERE p.active = TRUE
              AND (p.name ILIKE :q OR p.internal_name ILIKE :q OR p.sku ILIKE :q)
            ORDER BY (p.name ILIKE :prefix) DESC, p.name
            LIMIT :limit
        """), {'q': f'%{search}%', 'prefix': f'{search}%', 'limit': limit}).mappings().all()
    return jsonify({'products': [dict(r) for r in rows]})


@bp.route('/production-products/<int:product_id>/units', methods=['GET'])
@production_template_required
def production_product_units(product_id):
    """Units this product can be produced in: its base unit plus every unit that converts to it."""
    with get_engine().connect() as conn:
        choices = load_unit_choices(conn, [product_id]).get(product_id, [])
    return jsonify(choices)
