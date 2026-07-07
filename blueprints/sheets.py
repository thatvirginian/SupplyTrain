# =============================================================================
# blueprints/sheets.py
# =============================================================================
# API routes for count/order sheet management.
#
# Routes:
#   GET  /api/sheet-templates                          — list templates
#   POST /api/sheet-templates                          — create template
#   GET  /api/sheet-templates/<id>                     — template detail
#   PUT  /api/sheet-templates/<id>                     — update template
#   POST /api/sheet-templates/<id>/locations           — assign to location
#   DELETE /api/sheet-templates/<id>/locations/<loc>   — unassign location
#   POST /api/sheet-sections                           — create section
#   PUT  /api/sheet-sections/<id>                      — update section
#   DELETE /api/sheet-sections/<id>                    — delete section
#   POST /api/sheet-sections/<id>/items                — add product to section
#   DELETE /api/sheet-section-items/<id>               — remove product
#   GET  /api/sheet-submissions                        — list submissions
#   POST /api/sheet-submissions                        — create submission
#   GET  /api/sheet-submissions/<id>                   — submission detail
#   PUT  /api/sheet-submissions/<id>                   — save draft entries
#   POST /api/sheet-submissions/<id>/submit            — submit + generate orders
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
from functools import wraps
import logging
from datetime import date

logger = logging.getLogger(__name__)

bp = Blueprint('sheets', __name__, url_prefix='/api')


# ── Role constants ────────────────────────────────────────────────────────────

ADMIN        = 'admin'
GM           = 'gm'
STORE        = 'store'
COMMISSARY   = 'commissary'
COMM_GM      = 'commissary_gm'
READONLY     = 'readonly'

ALL_ROLES    = [ADMIN, GM, STORE, COMMISSARY, COMM_GM, READONLY]
STORE_ROLES  = [ADMIN, GM, STORE]                    # store-side access
COMM_ROLES   = [ADMIN, COMM_GM, COMMISSARY]          # commissary-side access
MANAGE_ROLES = [ADMIN, GM, COMM_GM]                  # can edit orders
STAFF_ROLES  = [ADMIN, GM, STORE, COMMISSARY, COMM_GM]  # any active user


def _has_role(*roles):
    """Check if current user has any of the given roles."""
    user_roles = g.user.get('roles', [])
    return any(r in user_roles for r in roles)


def _user_roles():
    return g.user.get('roles', [])


def _is_admin():
    return ADMIN in _user_roles()


def _is_comm():
    """True for commissary or commissary_gm."""
    return any(r in _user_roles() for r in [COMM_GM, COMMISSARY])


# ── Auth decorators ───────────────────────────────────────────────────────────

def admin_required(f):
    """Admin only."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN):
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


def manage_required(f):
    """Admin, GM, or Commissary GM — can edit orders and manage data."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, GM, COMM_GM):
            return jsonify({'error': 'Manager access required'}), 403
        return f(*args, **kwargs)
    return decorated


def staff_required(f):
    """Any authenticated user except readonly."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, GM, STORE, COMMISSARY, COMM_GM):
            return jsonify({'error': 'Access required'}), 403
        return f(*args, **kwargs)
    return decorated


def store_required(f):
    """Admin, GM, or Store — store-side access."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, GM, STORE):
            return jsonify({'error': 'Store access required'}), 403
        return f(*args, **kwargs)
    return decorated


def comm_required(f):
    """Admin, Commissary GM, or Commissary — commissary-side access."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, COMM_GM, COMMISSARY):
            return jsonify({'error': 'Commissary access required'}), 403
        return f(*args, **kwargs)
    return decorated


def comm_manage_required(f):
    """Admin or Commissary GM — can manage commissary templates and orders."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, COMM_GM):
            return jsonify({'error': 'Commissary manager access required'}), 403
        return f(*args, **kwargs)
    return decorated


def comm_item_edit_required(f):
    """
    Admin, GM, Commissary GM can edit anything.
    Commissary can only edit order_quantity and is_short (not delete).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, GM, COMM_GM, COMMISSARY):
            return jsonify({'error': 'Access required'}), 403
        return f(*args, **kwargs)
    return decorated


def any_role_required(f):
    """Any role including readonly."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(*ALL_ROLES):
            return jsonify({'error': 'Authentication required'}), 403
        return f(*args, **kwargs)
    return decorated


def get_engine():
    from flask import current_app
    return current_app.config['ENGINE']


def _get_user_location(conn):
    """Get location_id for staff user from locations.contact_email."""
    email = g.user.get('email', '').lower()

    row = conn.execute(text("""
        SELECT store_guid FROM locations WHERE LOWER(contact_email) = :email
    """), {'email': email}).fetchone()
    return str(row.store_guid) if row else None


# =============================================================================
# Sheet Templates — list / create
# =============================================================================

@bp.route('/locations', methods=['GET'])
@staff_required
def list_locations():
    """List all locations for dropdowns and assignment."""
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT
                store_guid::text AS store_guid,
                location_name,
                route,
                abbreviation
            FROM locations
            ORDER BY location_name
        """)).mappings().all()
    return jsonify([dict(r) for r in rows])


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


# =============================================================================
# Sheet Submissions — list / create
# =============================================================================

@bp.route('/sheet-submissions', methods=['GET'])
@store_required
def list_sheet_submissions():
    """
    List submissions. Admin sees all or filtered by location.
    Staff sees only their location.
    """
    roles       = g.user.get('roles', [])
    is_admin    = 'admin' in roles
    location_id = request.args.get('location_id')
    status      = request.args.get('status')
    template_id = request.args.get('template_id', type=int)
    show_inactive = request.args.get('show_inactive', 'false').lower() == 'true'
    page        = request.args.get('page', 1, type=int)
    per_page    = request.args.get('per_page', 20, type=int)
    offset      = (page - 1) * per_page

    with get_engine().connect() as conn:
        if not is_admin:
            location_id = _get_user_location(conn)

    filters = ['ss.active = TRUE'] if not show_inactive else []
    params  = {'limit': per_page, 'offset': offset}

    if location_id:
        filters.append('ss.location_id = :location_id')
        params['location_id'] = location_id
    if status:
        filters.append('ss.status = :status')
        params['status'] = status
    if template_id:
        filters.append('ss.template_id = :template_id')
        params['template_id'] = template_id

    where = ('WHERE ' + ' AND '.join(filters)) if filters else ''

    with get_engine().connect() as conn:
        total = conn.execute(text(f"""
            SELECT COUNT(*) FROM sheet_submissions ss {where}
        """), params).scalar()

        rows = conn.execute(text(f"""
            SELECT
                ss.id, ss.template_id, ss.location_id,
                ss.count_date, ss.status,
                ss.submitted_by, ss.submitted_at,
                ss.notes, ss.created_at,
                st.name AS template_name,
                l.location_name,
                COUNT(se.id) AS entry_count
            FROM sheet_submissions ss
            JOIN sheet_templates st ON ss.template_id = st.id
            LEFT JOIN locations l   ON l.store_guid::text = ss.location_id
            LEFT JOIN sheet_entries se ON se.submission_id = ss.id
            {where}
            GROUP BY ss.id, st.name, l.location_name
            ORDER BY ss.count_date DESC, ss.created_at DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return jsonify({
        'total':       total,
        'page':        page,
        'per_page':    per_page,
        'pages':       max(1, (total + per_page - 1) // per_page),
        'submissions': [dict(r) for r in rows],
    })


@bp.route('/sheet-submissions', methods=['POST'])
@store_required
def create_sheet_submission():
    """
    Open a new sheet submission.
    If a draft already exists for this template/location/date, return it.
    """
    data        = request.get_json(force=True)
    template_id = data.get('template_id')
    location_id = data.get('location_id')
    count_date  = data.get('count_date', str(date.today()))

    if not template_id:
        return jsonify({'error': 'template_id is required'}), 400

    roles    = g.user.get('roles', [])
    is_admin = 'admin' in roles

    with get_engine().connect() as conn:
        if not is_admin or not location_id:
            location_id = _get_user_location(conn)

    if not location_id:
        return jsonify({'error': 'Could not determine location'}), 400

    try:
        with get_engine().begin() as conn:
            # Check for existing draft
            existing = conn.execute(text("""
                SELECT id FROM sheet_submissions
                WHERE template_id  = :template_id
                AND location_id    = :location_id
                AND count_date     = :count_date
                AND status         = 'draft'
                LIMIT 1
            """), {
                'template_id': template_id,
                'location_id': location_id,
                'count_date':  count_date,
            }).fetchone()

            if existing:
                return jsonify({'id': existing.id, 'existing': True}), 200

            # Create new submission
            result = conn.execute(text("""
                INSERT INTO sheet_submissions (
                    template_id, location_id, count_date, submitted_by
                ) VALUES (
                    :template_id, :location_id, :count_date, :submitted_by
                )
                RETURNING id
            """), {
                'template_id':  template_id,
                'location_id':  location_id,
                'count_date':   count_date,
                'submitted_by': g.user.get('email'),
            })
            submission_id = result.fetchone().id
        return jsonify({'id': submission_id, 'existing': False}), 201
    except Exception as e:
        logger.error(f'create_sheet_submission: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Sheet Submissions — detail / save draft
# =============================================================================

@bp.route('/sheet-submissions/<int:submission_id>', methods=['GET'])
@store_required
def get_sheet_submission(submission_id):
    """
    Full submission detail with template structure and current entries.
    Returns the template sections/items with any saved counts merged in.
    """
    with get_engine().connect() as conn:
        submission = conn.execute(text("""
            SELECT
                ss.id, ss.template_id, ss.location_id,
                ss.count_date, ss.status,
                ss.submitted_by, ss.submitted_at, ss.notes,
                st.name AS template_name,
                l.location_name
            FROM sheet_submissions ss
            JOIN sheet_templates st ON ss.template_id = st.id
            LEFT JOIN locations l   ON l.store_guid::text = ss.location_id
            WHERE ss.id = :id
        """), {'id': submission_id}).mappings().fetchone()

        if not submission:
            return jsonify({'error': 'Submission not found'}), 404

        # Template sections with items
        sections = conn.execute(text("""
            SELECT
                sec.id    AS section_id,
                sec.name  AS section_name,
                sec.sort_order AS section_sort,
                ssi.id    AS item_id,
                ssi.product_id,
                ssi.sort_order AS item_sort,
                p.name    AS product_name,
                p.base_unit_id,
                u.name    AS base_unit,
                c.name    AS category
            FROM sheet_sections sec
            JOIN sheet_section_items ssi ON ssi.section_id   = sec.id
            JOIN products p              ON ssi.product_id   = p.id
            LEFT JOIN units u            ON p.base_unit_id   = u.id
            LEFT JOIN product_categories c ON p.category_id = c.id
            WHERE sec.template_id = :template_id
            ORDER BY sec.sort_order, ssi.sort_order
        """), {'template_id': submission['template_id']}).mappings().all()

        # Existing entries for this submission — one per product per unit
        entries = conn.execute(text("""
            SELECT
                se.product_id,
                se.quantity,
                se.unit_id,
                se.base_quantity,
                se.base_unit_id,
                se.notes,
                u.name AS unit_name
            FROM sheet_entries se
            LEFT JOIN units u ON se.unit_id = u.id
            WHERE se.submission_id = :id
        """), {'id': submission_id}).mappings().all()

        # Available units per product (for dropdowns)
        product_ids = list(set(s['product_id'] for s in sections))
        available_units = {}
        if product_ids:
            unit_rows = conn.execute(text("""
                SELECT DISTINCT
                    COALESCE(uc.product_id, p.id) AS product_id,
                    u.id   AS unit_id,
                    u.name AS unit_name,
                    u.display AS unit_display
                FROM products p
                JOIN unit_conversions uc ON
                    (uc.product_id = p.id OR uc.product_id IS NULL)
                JOIN units u ON uc.from_unit_id = u.id
                WHERE p.id = ANY(:product_ids)

                UNION

                SELECT p.id, u.id, u.name, u.display
                FROM products p
                JOIN units u ON p.base_unit_id = u.id
                WHERE p.id = ANY(:product_ids)

                ORDER BY product_id, unit_name
            """), {'product_ids': product_ids}).mappings().all()

            for row in unit_rows:
                pid = row['product_id']
                if pid not in available_units:
                    available_units[pid] = []
                available_units[pid].append({
                    'unit_id':      row['unit_id'],
                    'unit_name':    row['unit_name'],
                    'unit_display': row['unit_display'],
                })

        # Active vendor items per product for this location
        vendor_items = {}
        if product_ids:
            # Also fetch effective par levels for the submission date
            from datetime import datetime
            count_date = submission['count_date']
            if hasattr(count_date, 'strftime'):
                dow = count_date.weekday()  # 0=Monday in Python
                # Convert to 0=Sunday
                dow = (dow + 1) % 7
            else:
                try:
                    dt = datetime.strptime(str(count_date)[:10], '%Y-%m-%d')
                    dow = (dt.weekday() + 1) % 7
                except:
                    dow = None

            par_rows = conn.execute(text("""
                SELECT DISTINCT ON (ppl.product_id)
                    ppl.product_id,
                    COALESCE(ppl.override_qty,      ppl.recommended_qty)      AS par_qty,
                    COALESCE(ppl.override_unit_id,  ppl.recommended_unit_id)  AS unit_id,
                    COALESCE(ou.name,               ru.name)                  AS unit_name
                FROM product_par_levels ppl
                LEFT JOIN units ru ON ppl.recommended_unit_id = ru.id
                LEFT JOIN units ou ON ppl.override_unit_id    = ou.id
                WHERE ppl.product_id  = ANY(:product_ids)
                AND ppl.location_id   = :location_id
                AND (ppl.day_of_week  = :dow OR ppl.day_of_week IS NULL)
                ORDER BY ppl.product_id, ppl.day_of_week NULLS LAST
            """), {
                'product_ids': product_ids,
                'location_id': submission['location_id'],
                'dow':         dow,
            }).mappings().all()

            par_map = {r['product_id']: dict(r) for r in par_rows}

            vi_rows = conn.execute(text("""
                SELECT
                    vi.product_id,
                    vi.id          AS vendor_item_id,
                    vi.vendor_code,
                    vi.order_unit_id,
                    vi.order_quantity,
                    vi.price,
                    v.name         AS vendor_name,
                    u.name         AS order_unit
                FROM vendor_items vi
                JOIN vendors v    ON vi.vendor_id     = v.id
                LEFT JOIN units u ON vi.order_unit_id = u.id
                WHERE vi.product_id = ANY(:product_ids)
                AND vi.active = TRUE
            """), {'product_ids': product_ids}).mappings().all()

            for row in vi_rows:
                vendor_items[row['product_id']] = dict(row)

    # Build entry map: (product_id, unit_id) → entry
    entry_map = {}
    for e in entries:
        key = (e['product_id'], e['unit_id'])
        entry_map[key] = dict(e)

    # Build count units map for submission items
    with get_engine().connect() as conn2:
        product_ids = list(set(s['product_id'] for s in sections))
        item_ids    = list(set(s['item_id'] for s in sections))
        count_units_map = {}
        if item_ids:
            cu_rows = conn2.execute(text("""
                SELECT ssiu.id, ssiu.item_id, ssiu.unit_id,
                       u.name AS unit_name, u.display AS unit_display
                FROM sheet_section_item_units ssiu
                JOIN units u ON ssiu.unit_id = u.id
                WHERE ssiu.item_id = ANY(:item_ids)
                ORDER BY ssiu.item_id, ssiu.sort_order
            """), {'item_ids': item_ids}).mappings().all()
            for cu in cu_rows:
                iid = cu['item_id']
                if iid not in count_units_map:
                    count_units_map[iid] = []
                count_units_map[iid].append(dict(cu))

    # Build section structure with merged entries
    section_map = {}
    for row in sections:
        sid = row['section_id']
        if sid not in section_map:
            section_map[sid] = {
                'id':         sid,
                'name':       row['section_name'],
                'sort_order': row['section_sort'],
                'items':      [],
            }
        pid    = row['product_id']
        iid    = row['item_id']
        # If no count units defined for this item, fall back to base unit
        item_count_units = count_units_map.get(iid, [])
        if not item_count_units:
            item_count_units = [{
                'unit_id':      row['base_unit_id'],
                'unit_name':    row['base_unit'],
                'unit_display': row['base_unit'],
                'is_default':   True,
            }]

        # Merge saved quantities into count units
        for cu in item_count_units:
            key   = (pid, cu['unit_id'])
            saved = entry_map.get(key)
            cu['saved_quantity'] = float(saved['quantity']) if saved and saved['quantity'] is not None else None

        section_map[sid]['items'].append({
            'item_id':         iid,
            'product_id':      pid,
            'product_name':    row['product_name'],
            'base_unit':       row['base_unit'],
            'base_unit_id':    row['base_unit_id'],
            'category':        row['category'],
            'sort_order':      row['item_sort'],
            'count_units':     item_count_units,
            'par':             par_map.get(pid),
            'available_units': available_units.get(pid, []),
            'vendor_item':     vendor_items.get(pid),
        })

    result = dict(submission)
    result['sections'] = sorted(section_map.values(), key=lambda s: s['sort_order'])
    return jsonify(result)


@bp.route('/sheet-submissions/<int:submission_id>', methods=['PUT'])
@store_required
def save_draft_entries(submission_id):
    """
    Save draft entries. Batched version — 3 queries regardless of entry count.
    """
    data    = request.get_json(force=True)
    entries = data.get('entries', [])

    with get_engine().connect() as conn:
        sub = conn.execute(text("""
            SELECT status FROM sheet_submissions WHERE id = :id
        """), {'id': submission_id}).fetchone()

    if not sub:
        return jsonify({'error': 'Submission not found'}), 404

    roles    = g.user.get('roles', [])
    is_admin = 'admin' in roles
    if sub.status == 'submitted' and not is_admin:
        return jsonify({'error': 'Cannot edit a submitted sheet'}), 400

    # Filter valid entries
    valid = [
        e for e in entries
        if e.get('product_id') and e.get('quantity') is not None and e.get('unit_id')
    ]
    if not valid:
        return jsonify({'status': 'ok'})

    try:
        with get_engine().begin() as conn:
            product_ids = list({e['product_id'] for e in valid})
            unit_ids    = list({e['unit_id']    for e in valid})

            # ── BATCH 1: all base unit IDs for these products ─────────────────
            prod_rows = conn.execute(text("""
                SELECT id, base_unit_id FROM products
                WHERE id = ANY(:ids)
            """), {'ids': product_ids}).fetchall()
            base_unit_map = {r.id: r.base_unit_id for r in prod_rows}

            # ── BATCH 2: all relevant unit conversions ────────────────────────
            base_unit_ids = list(set(base_unit_map.values()))
            conv_rows = conn.execute(text("""
                SELECT from_unit_id, to_unit_id, conversion, product_id
                FROM unit_conversions
                WHERE (from_unit_id = ANY(:unit_ids) OR to_unit_id = ANY(:unit_ids))
                AND (from_unit_id = ANY(:base_ids) OR to_unit_id = ANY(:base_ids))
                AND (product_id = ANY(:product_ids) OR product_id IS NULL)
                ORDER BY product_id NULLS LAST
            """), {
                'unit_ids':   unit_ids,
                'base_ids':   base_unit_ids,
                'product_ids': product_ids,
            }).fetchall()

            # Build conversion map: (from_unit, to_unit, product_id) → conversion
            # product-specific entries come first (ordered by product_id NULLS LAST)
            conv_map = {}
            for r in conv_rows:
                key = (r.from_unit_id, r.to_unit_id, r.product_id)
                conv_map[key] = float(r.conversion)
                # Also store global fallback key
                global_key = (r.from_unit_id, r.to_unit_id, None)
                if global_key not in conv_map:
                    conv_map[global_key] = float(r.conversion)

            def get_conversion(from_uid, to_uid, product_id):
                # Product-specific first, then global, then inverse
                for pid in [product_id, None]:
                    v = conv_map.get((from_uid, to_uid, pid))
                    if v is not None:
                        return v
                    v = conv_map.get((to_uid, from_uid, pid))
                    if v is not None:
                        return 1.0 / v
                return None

            # ── Calculate base quantities in Python ───────────────────────────
            rows_to_upsert = []
            for e in valid:
                pid          = e['product_id']
                unit_id      = e['unit_id']
                quantity     = float(e['quantity'])
                base_unit_id = base_unit_map.get(pid)
                base_quantity = None

                if base_unit_id:
                    if unit_id == base_unit_id:
                        base_quantity = quantity
                    else:
                        factor = get_conversion(unit_id, base_unit_id, pid)
                        if factor:
                            base_quantity = quantity * factor

                rows_to_upsert.append({
                    'submission_id': submission_id,
                    'product_id':    pid,
                    'quantity':      quantity,
                    'unit_id':       unit_id,
                    'base_quantity': base_quantity,
                    'base_unit_id':  base_unit_id,
                    'notes':         e.get('notes'),
                })

            # ── BATCH 3: upsert all entries at once ───────────────────────────
            conn.execute(text("""
                INSERT INTO sheet_entries (
                    submission_id, product_id,
                    quantity, unit_id,
                    base_quantity, base_unit_id,
                    notes
                ) VALUES (
                    :submission_id, :product_id,
                    :quantity, :unit_id,
                    :base_quantity, :base_unit_id,
                    :notes
                )
                ON CONFLICT (submission_id, product_id, unit_id) DO UPDATE SET
                    quantity      = EXCLUDED.quantity,
                    base_quantity = EXCLUDED.base_quantity,
                    base_unit_id  = EXCLUDED.base_unit_id,
                    notes         = EXCLUDED.notes,
                    updated_at    = NOW()
            """), rows_to_upsert)

            conn.execute(text("""
                UPDATE sheet_submissions SET updated_at = NOW() WHERE id = :id
            """), {'id': submission_id})

        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'save_draft_entries: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Sheet Submissions — submit
# =============================================================================

@bp.route('/sheet-submissions/<int:submission_id>', methods=['DELETE'])
@store_required
def delete_sheet_submission(submission_id):
    """
    Delete a sheet submission.
    Staff can only delete drafts.
    Admin can delete any status.
    """
    roles    = g.user.get('roles', [])
    is_admin = 'admin' in roles

    try:
        with get_engine().begin() as conn:
            sub = conn.execute(text("""
                SELECT status FROM sheet_submissions WHERE id = :id
            """), {'id': submission_id}).fetchone()

            if not sub:
                return jsonify({'error': 'Submission not found'}), 404
            if sub.status == 'submitted' and not is_admin:
                return jsonify({'error': 'Only admin can delete submitted sheets'}), 403

            # Delete cascade handles sheet_entries
            conn.execute(text("""
                DELETE FROM sheet_submissions WHERE id = :id
            """), {'id': submission_id})

        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_sheet_submission: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-submissions/<int:submission_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_submission_active(submission_id):
    """Toggle a sheet submission active/inactive."""
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE sheet_submissions SET
                    active     = NOT active,
                    updated_at = NOW()
                WHERE id = :id
            """), {'id': submission_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'toggle_submission_active: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-submissions/<int:submission_id>/submit', methods=['POST'])
@store_required
def submit_sheet(submission_id):
    """
    Submit a count sheet. Generates purchase orders grouped by vendor.
    Batched version — replaces N-query loops with set-based SQL.
    """
    import math
    from datetime import datetime

    data          = request.get_json(force=True) or {}
    expected_date = data.get('expected_date') or None

    with get_engine().connect() as conn:
        sub = conn.execute(text("""
            SELECT ss.id, ss.template_id, ss.location_id, ss.count_date, ss.status,
                   st.is_commissary
            FROM sheet_submissions ss
            JOIN sheet_templates st ON ss.template_id = st.id
            WHERE ss.id = :id
        """), {'id': submission_id}).mappings().fetchone()

    if not sub:
        return jsonify({'error': 'Submission not found'}), 404
    if sub['status'] == 'submitted':
        return jsonify({'error': 'Already submitted'}), 400

    # Day of week (0=Sunday)
    try:
        count_date = sub['count_date']
        if hasattr(count_date, 'weekday'):
            dow = (count_date.weekday() + 1) % 7
        else:
            dt  = datetime.strptime(str(count_date)[:10], '%Y-%m-%d')
            dow = (dt.weekday() + 1) % 7
    except Exception:
        dow = None

    try:
        import time
        t0 = time.time()
        with get_engine().begin() as conn:

            # ── BATCH QUERY 1: entries + vendor info ──────────────────────────
            # Single query returns all entries with vendor info resolved
            entries = conn.execute(text("""
                SELECT
                    se.product_id,
                    SUM(se.base_quantity)   AS total_base_quantity,
                    MAX(se.base_unit_id)    AS base_unit_id,
                    p.name                  AS product_name,
                    COALESCE(p.order_rounding_threshold, 0.5) AS order_rounding_threshold,
                    COALESCE(lvi_vi.id,            vi_g.id)            AS vendor_item_id,
                    COALESCE(lvi_vi.vendor_code,   vi_g.vendor_code)   AS vendor_code,
                    COALESCE(lvi_vi.order_unit_id, vi_g.order_unit_id) AS order_unit_id,
                    COALESCE(lvi_vi.order_quantity,vi_g.order_quantity) AS vendor_qty_per_unit,
                    COALESCE(lvi_vi.price,         vi_g.price)         AS price,
                    COALESCE(lvi_v.id,             vi_g_v.id)          AS vendor_id,
                    COALESCE(lvi_v.name,           vi_g_v.name)        AS vendor_name,
                    COALESCE(lvi_v.is_commissary,  vi_g_v.is_commissary, FALSE) AS is_commissary,
                    COALESCE(ou_l.name,            ou_g.name)          AS order_unit
                FROM sheet_entries se
                JOIN products p ON se.product_id = p.id
                LEFT JOIN location_vendor_items lvi
                    ON lvi.product_id = p.id AND lvi.location_id = :location_id
                LEFT JOIN vendor_items lvi_vi ON lvi.vendor_item_id  = lvi_vi.id
                LEFT JOIN vendors lvi_v       ON lvi_vi.vendor_id    = lvi_v.id
                LEFT JOIN units ou_l          ON lvi_vi.order_unit_id = ou_l.id
                LEFT JOIN vendor_items vi_g
                    ON vi_g.product_id = p.id AND vi_g.active = TRUE
                LEFT JOIN vendors vi_g_v ON vi_g.vendor_id     = vi_g_v.id
                LEFT JOIN units ou_g     ON vi_g.order_unit_id = ou_g.id
                WHERE se.submission_id = :id
                GROUP BY se.product_id, p.name, p.order_rounding_threshold,
                         lvi_vi.id, lvi_vi.vendor_code, lvi_vi.order_unit_id, lvi_vi.order_quantity, lvi_vi.price,
                         lvi_v.id, lvi_v.name, lvi_v.is_commissary, ou_l.name,
                         vi_g.id,  vi_g.vendor_code,  vi_g.order_unit_id,  vi_g.order_quantity,  vi_g.price,
                         vi_g_v.id, vi_g_v.name, vi_g_v.is_commissary, ou_g.name
            """), {'id': submission_id, 'location_id': sub['location_id']}).mappings().all()
            logger.info(f'submit_sheet [{submission_id}] entries query: {time.time()-t0:.2f}s')
            t1 = time.time()

            # Build lookup dicts — keyed by product_id for O(1) access later
            entries_by_product = {e['product_id']: e for e in entries}
            product_ids = list(entries_by_product.keys())

            if not product_ids:
                return jsonify({'error': 'No entries to submit'}), 400

            # ── BATCH QUERY 2: par levels for all products at once ─────────────
            par_rows = conn.execute(text("""
                WITH par_data AS (
                    SELECT
                        ppl.product_id,
                        ppl.day_of_week,
                        COALESCE(ppl.override_qty,      ppl.recommended_qty)     AS par_qty,
                        COALESCE(ppl.override_unit_id,  ppl.recommended_unit_id) AS par_unit_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY ppl.product_id
                            ORDER BY ppl.day_of_week NULLS LAST
                        ) AS rn
                    FROM product_par_levels ppl
                    WHERE ppl.product_id  = ANY(:product_ids)
                    AND ppl.location_id   = :location_id
                    AND (ppl.day_of_week  = :dow OR ppl.day_of_week IS NULL)
                )
                SELECT pd.product_id, pd.par_qty, pd.par_unit_id,
                       uc.conversion, uc.from_unit_id, uc.to_unit_id
                FROM par_data pd
                LEFT JOIN products p ON pd.product_id = p.id
                LEFT JOIN unit_conversions uc ON (
                    (uc.from_unit_id = pd.par_unit_id AND uc.to_unit_id = p.base_unit_id)
                    OR
                    (uc.from_unit_id = p.base_unit_id AND uc.to_unit_id = pd.par_unit_id)
                )
                AND (uc.product_id = pd.product_id OR uc.product_id IS NULL)
                WHERE pd.rn = 1
                ORDER BY pd.product_id, uc.product_id NULLS LAST,
                         CASE WHEN uc.to_unit_id = p.base_unit_id THEN 0 ELSE 1 END
            """), {
                'product_ids': product_ids,
                'location_id': sub['location_id'],
                'dow':         dow,
            }).mappings().all()
            logger.info(f'submit_sheet [{submission_id}] par query: {time.time()-t1:.2f}s')
            t2 = time.time()

            # Build par map — keyed by product_id
            par_map = {}
            for row in par_rows:
                pid = row['product_id']
                if pid not in par_map:  # first row wins (best conversion match)
                    par_map[pid] = dict(row)

            # ── BATCH QUERY 3: unit conversions for all order units at once ────
            # Collect all unique (base_unit, order_unit, product) combos
            conv_keys = set()
            for e in entries:
                if e['order_unit_id'] and e['base_unit_id']:
                    conv_keys.add((e['base_unit_id'], e['order_unit_id'], e['product_id']))

            vendor_conv_map = {}  # (base_unit_id, order_unit_id, product_id) → factor
            if conv_keys:
                # Fetch all potentially relevant conversions in one query
                # then match in Python to avoid unnest parameter conflicts
                all_unit_ids = list(set(
                    [k[0] for k in conv_keys] + [k[1] for k in conv_keys]
                ))
                all_prod_ids = list(set(k[2] for k in conv_keys))

                conv_rows = conn.execute(text("""
                    SELECT uc.conversion, uc.from_unit_id, uc.to_unit_id, uc.product_id
                    FROM unit_conversions uc
                    WHERE (
                        uc.from_unit_id = ANY(:unit_ids)
                        OR uc.to_unit_id = ANY(:unit_ids)
                    )
                    AND (uc.product_id = ANY(:prod_ids) OR uc.product_id IS NULL)
                    ORDER BY uc.product_id NULLS LAST
                """), {
                    'unit_ids': all_unit_ids,
                    'prod_ids': all_prod_ids,
                }).mappings().all()

                # Match conversions to each (base_unit, order_unit, product) combo in Python
                for base_uid, order_uid, pid in conv_keys:
                    # Look for product-specific first, then global
                    best = None
                    for row in conv_rows:
                        matches = (
                            (row['from_unit_id'] == base_uid and row['to_unit_id'] == order_uid) or
                            (row['from_unit_id'] == order_uid and row['to_unit_id'] == base_uid)
                        )
                        if not matches:
                            continue
                        if best is None or (row['product_id'] == pid and best['product_id'] is None):
                            best = row
                    if best:
                        if best['from_unit_id'] == base_uid:
                            factor = float(best['conversion'])
                        else:
                            factor = 1.0 / float(best['conversion'])
                        vendor_conv_map[(base_uid, order_uid, pid)] = factor
            logger.info(f'submit_sheet [{submission_id}] conv query: {time.time()-t2:.2f}s')
            t3 = time.time()

            # ── BATCH QUERY 4: vendor snapshot update ─────────────────────────
            conn.execute(text("""
                UPDATE sheet_entries SET
                    vendor_item_id = :vendor_item_id,
                    vendor_code    = :vendor_code,
                    vendor_name    = :vendor_name,
                    order_unit_id  = :order_unit_id,
                    updated_at     = NOW()
                WHERE submission_id = :submission_id
                AND product_id = :product_id
            """), [
                {
                    'submission_id':  submission_id,
                    'product_id':     e['product_id'],
                    'vendor_item_id': e.get('vendor_item_id'),
                    'vendor_code':    e.get('vendor_code'),
                    'vendor_name':    e.get('vendor_name'),
                    'order_unit_id':  e.get('order_unit_id'),
                }
                for e in entries
            ])
            logger.info(f'submit_sheet [{submission_id}] vendor snapshot: {time.time()-t3:.2f}s')
            t4 = time.time()

            # ── Python: calculate order quantities ────────────────────────────
            # All the math happens here — no more per-product DB calls
            order_calc = {}  # product_id → { order_qty, order_base, par_qty, par_unit_id, par_base_qty }

            for e in entries:
                pid          = e['product_id']
                par          = par_map.get(pid)
                on_hand_base = float(e['total_base_quantity'] or 0)
                base_unit_id = e['base_unit_id']

                # Convert par to base units
                par_base = 0.0
                par_qty_snap     = None
                par_unit_id_snap = None
                par_base_qty_snap = None

                if par and par['par_qty']:
                    par_qty_snap     = par['par_qty']
                    par_unit_id_snap = par['par_unit_id']
                    if par['conversion']:
                        if par['to_unit_id'] == base_unit_id:
                            par_base = float(par['par_qty']) * float(par['conversion'])
                        else:
                            par_base = float(par['par_qty']) / float(par['conversion'])
                    else:
                        par_base = float(par['par_qty'])
                    par_base_qty_snap = par_base

                # Order qty in base units
                order_base = max(0.0, par_base - on_hand_base)

                # Convert to vendor order unit using pre-fetched conversion
                order_qty = order_base
                if e['order_unit_id'] and base_unit_id and order_base > 0:
                    key    = (base_unit_id, e['order_unit_id'], pid)
                    factor = vendor_conv_map.get(key)
                    if factor:
                        raw_qty   = order_base * factor
                        threshold = float(e.get('order_rounding_threshold') or 0.5)
                        whole     = math.floor(raw_qty)
                        frac      = raw_qty - whole
                        order_qty = whole + 1 if frac >= threshold else whole
                        order_qty = max(1, order_qty) if raw_qty > 0 else 0

                order_calc[pid] = {
                    'order_qty':        order_qty,
                    'order_base':       order_base,
                    'par_qty':          par_qty_snap,
                    'par_unit_id':      par_unit_id_snap,
                    'par_base_qty':     par_base_qty_snap,
                }

            # ── Group by vendor and create POs ────────────────────────────────
            vendor_entries = {}
            for e in entries:
                if not e['vendor_id']:
                    continue
                vid = e['vendor_id']
                if vid not in vendor_entries:
                    vendor_entries[vid] = {
                        'vendor_id':    vid,
                        'vendor_name':  e['vendor_name'],
                        'is_commissary': e['is_commissary'],
                        'items':        [],
                    }
                vendor_entries[vid]['items'].append(e)

            po_ids            = []
            commissary_po_ids = []
            po_item_map       = {}  # product_id → (order_qty, order_unit_id) for snapshot

            for vid, vdata in vendor_entries.items():
                is_comm = vdata['is_commissary']

                po_result = conn.execute(text("""
                    INSERT INTO purchase_orders (
                        location_id, order_date, expected_date, vendor_id,
                        status, created_by, is_commissary
                    ) VALUES (
                        :location_id, :order_date, :expected_date, :vendor_id,
                        'draft', :created_by, :is_commissary
                    )
                    RETURNING id
                """), {
                    'location_id':   sub['location_id'],
                    'order_date':    sub['count_date'],
                    'expected_date': expected_date,
                    'vendor_id':     vid,
                    'created_by':    g.user.get('email'),
                    'is_commissary': is_comm,
                })
                po_id = po_result.fetchone().id
                if is_comm:
                    commissary_po_ids.append(po_id)
                else:
                    po_ids.append(po_id)

                # Commissary section mapping
                comm_section_map = {}
                if is_comm:
                    comm_template = conn.execute(text("""
                        SELECT ct.id FROM comm_order_templates ct
                        WHERE ct.location_id = :location_id
                        AND ct.vendor_id     = :vendor_id
                        AND ct.active        = TRUE
                        LIMIT 1
                    """), {
                        'location_id': sub['location_id'],
                        'vendor_id':   vid,
                    }).fetchone()

                    if comm_template:
                        tmpl_sections = conn.execute(text("""
                            SELECT s.id AS section_id, s.name AS section_name,
                                   s.sort_order, i.product_id
                            FROM comm_order_template_sections s
                            LEFT JOIN comm_order_template_items i ON i.section_id = s.id
                            WHERE s.template_id = :template_id
                            ORDER BY s.sort_order, i.sort_order
                        """), {'template_id': comm_template.id}).mappings().all()

                        product_section_name = {}
                        section_sort = {}
                        for row in tmpl_sections:
                            if row['product_id']:
                                product_section_name[row['product_id']] = row['section_name']
                            section_sort[row['section_name']] = row['sort_order']

                        needed_sections = {}
                        for item in vdata['items']:
                            sec_name = product_section_name.get(item['product_id'], 'Other')
                            if sec_name not in needed_sections:
                                needed_sections[sec_name] = section_sort.get(sec_name, 999)

                        po_section_ids = {}
                        for sec_name, sort_order in sorted(needed_sections.items(), key=lambda x: x[1]):
                            result = conn.execute(text("""
                                INSERT INTO comm_order_sections (purchase_order_id, name, sort_order)
                                VALUES (:po_id, :name, :sort_order)
                                RETURNING id
                            """), {'po_id': po_id, 'name': sec_name, 'sort_order': sort_order})
                            po_section_ids[sec_name] = result.fetchone().id

                        for item in vdata['items']:
                            sec_name = product_section_name.get(item['product_id'], 'Other')
                            comm_section_map[item['product_id']] = po_section_ids.get(sec_name)

                # ── Insert all PO items for this vendor ───────────────────────
                if vdata['items']:
                    conn.execute(text("""
                        INSERT INTO purchase_order_items (
                            purchase_order_id, product_id,
                            vendor_item_id, vendor_code, product_name,
                            order_unit_id, order_quantity, original_quantity,
                            base_quantity, base_unit_id,
                            unit_price, comm_section_id
                        ) VALUES (
                            :po_id, :product_id,
                            :vendor_item_id, :vendor_code, :product_name,
                            :order_unit_id, :order_quantity, :order_quantity,
                            :base_quantity, :base_unit_id,
                            :unit_price, :comm_section_id
                        )
                        ON CONFLICT (purchase_order_id, product_id) DO NOTHING
                    """), [
                        {
                            'po_id':           po_id,
                            'product_id':      item['product_id'],
                            'vendor_item_id':  item['vendor_item_id'],
                            'vendor_code':     item['vendor_code'],
                            'product_name':    item['product_name'],
                            'order_unit_id':   item['order_unit_id'],
                            'order_quantity':  order_calc.get(item['product_id'], {}).get('order_qty', 0),
                            'base_quantity':   order_calc.get(item['product_id'], {}).get('order_base', 0),
                            'base_unit_id':    item['base_unit_id'],
                            'unit_price':      item['price'],
                            'comm_section_id': comm_section_map.get(item['product_id']),
                        }
                        for item in vdata['items']
                    ])
                    # Track for inventory snapshot
                    for item in vdata['items']:
                        pid = item['product_id']
                        po_item_map[pid] = {
                            'order_quantity': order_calc.get(pid, {}).get('order_qty', 0),
                            'order_unit_id':  item['order_unit_id'],
                        }

            logger.info(f'submit_sheet [{submission_id}] PO creation: {time.time()-t4:.2f}s')
            t5 = time.time()

            # ── Create inventory submission header ────────────────────────────
            inv_sub_result = conn.execute(text("""
                INSERT INTO inventory_submissions (
                    sheet_submission_id, location_id, count_date,
                    source, status, submitted_by, submitted_at
                ) VALUES (
                    :sheet_submission_id, :location_id, :count_date,
                    'count_sheet', 'submitted', :submitted_by, NOW()
                )
                RETURNING id
            """), {
                'sheet_submission_id': submission_id,
                'location_id':         sub['location_id'],
                'count_date':          sub['count_date'],
                'submitted_by':        g.user.get('email'),
            })
            inv_submission_id = inv_sub_result.fetchone().id

            # ── BATCH: insert all inventory_counts ───────────────────────────
            inv_rows = [e for e in entries if e['total_base_quantity']]
            if inv_rows:
                conn.execute(text("""
                    INSERT INTO inventory_counts (
                        submission_id, inventory_submission_id,
                        location_id, product_id, count_date,
                        base_quantity, base_unit_id,
                        vendor_item_id, vendor_id, vendor_code,
                        par_qty, par_unit_id, par_base_qty,
                        order_qty, order_unit_id, entered_by
                    ) VALUES (
                        :submission_id, :inv_submission_id,
                        :location_id, :product_id, :count_date,
                        :base_quantity, :base_unit_id,
                        :vendor_item_id, :vendor_id, :vendor_code,
                        :par_qty, :par_unit_id, :par_base_qty,
                        :order_qty, :order_unit_id, :entered_by
                    )
                    ON CONFLICT (location_id, product_id, count_date) DO UPDATE SET
                        inventory_submission_id = EXCLUDED.inventory_submission_id,
                        base_quantity           = EXCLUDED.base_quantity,
                        vendor_item_id          = EXCLUDED.vendor_item_id,
                        vendor_id               = EXCLUDED.vendor_id,
                        vendor_code             = EXCLUDED.vendor_code,
                        par_qty                 = EXCLUDED.par_qty,
                        par_unit_id             = EXCLUDED.par_unit_id,
                        par_base_qty            = EXCLUDED.par_base_qty,
                        order_qty               = EXCLUDED.order_qty,
                        order_unit_id           = EXCLUDED.order_unit_id
                """), [
                    {
                        'submission_id':      submission_id,
                        'inv_submission_id':  inv_submission_id,
                        'location_id':        sub['location_id'],
                        'product_id':         e['product_id'],
                        'count_date':         sub['count_date'],
                        'base_quantity':      float(e['total_base_quantity']),
                        'base_unit_id':       e['base_unit_id'],
                        'vendor_item_id':     e.get('vendor_item_id'),
                        'vendor_id':          e.get('vendor_id'),
                        'vendor_code':        e.get('vendor_code'),
                        'par_qty':            order_calc.get(e['product_id'], {}).get('par_qty'),
                        'par_unit_id':        order_calc.get(e['product_id'], {}).get('par_unit_id'),
                        'par_base_qty':       order_calc.get(e['product_id'], {}).get('par_base_qty'),
                        'order_qty':          po_item_map.get(e['product_id'], {}).get('order_quantity'),
                        'order_unit_id':      po_item_map.get(e['product_id'], {}).get('order_unit_id'),
                        'entered_by':         g.user.get('email'),
                    }
                    for e in inv_rows
                ])

            # ── Lock the submission ───────────────────────────────────────────
            logger.info(f'submit_sheet [{submission_id}] inventory counts: {time.time()-t5:.2f}s')
            t6 = time.time()
            conn.execute(text("""
                UPDATE sheet_submissions SET
                    status       = 'submitted',
                    submitted_at = NOW(),
                    submitted_by = :submitted_by,
                    updated_at   = NOW()
                WHERE id = :id
            """), {'id': submission_id, 'submitted_by': g.user.get('email')})
            logger.info(f'submit_sheet [{submission_id}] TOTAL: {time.time()-t0:.2f}s')

        return jsonify({
            'status':                  'submitted',
            'po_ids':                  po_ids,
            'po_count':                len(po_ids),
            'commissary_po_ids':       commissary_po_ids,
            'commissary_po_count':     len(commissary_po_ids),
            'inventory_submission_id': inv_submission_id,
        })
    except Exception as e:
        logger.error(f'submit_sheet: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================


# =============================================================================
# Par Levels
# =============================================================================

@bp.route('/par-levels', methods=['GET'])
@store_required
def list_par_levels():
    """Get par levels for a location, optionally filtered by product_ids or vendor."""
    location_id = request.args.get('location_id')
    product_ids = request.args.getlist('product_id', type=int)
    vendor_id   = request.args.get('vendor_id', type=int)
    roles       = g.user.get('roles', [])
    is_admin    = 'admin' in roles

    with get_engine().connect() as conn:
        if not is_admin or not location_id:
            location_id = _get_user_location(conn)

        filters = ['ppl.location_id = :location_id']
        params  = {'location_id': location_id}

        if product_ids:
            filters.append('ppl.product_id = ANY(:product_ids)')
            params['product_ids'] = product_ids

        if vendor_id:
            # Filter by active vendor item for this location
            filters.append("""
                ppl.product_id IN (
                    SELECT vi.product_id
                    FROM vendor_items vi
                    LEFT JOIN location_vendor_items lvi
                        ON lvi.product_id   = vi.product_id
                        AND lvi.location_id = :location_id
                    LEFT JOIN vendor_items lvi_vi ON lvi.vendor_item_id = lvi_vi.id
                    WHERE COALESCE(lvi_vi.vendor_id, vi.vendor_id) = :vendor_id
                    AND (lvi.vendor_item_id IS NOT NULL OR vi.active = TRUE)
                )
            """)
            params['vendor_id'] = vendor_id

        where = ' AND '.join(filters)

        rows = conn.execute(text(f"""
            SELECT
                ppl.id,
                ppl.product_id,
                ppl.location_id,
                ppl.day_of_week,
                ppl.recommended_qty,
                ppl.recommended_at,
                ppl.override_qty,
                ppl.override_by,
                ppl.override_at,
                ppl.notes,
                p.name      AS product_name,
                ru.name     AS recommended_unit,
                ru.id       AS recommended_unit_id,
                ou.name     AS override_unit,
                ou.id       AS override_unit_id,
                COALESCE(ppl.override_qty,  ppl.recommended_qty) AS par_qty,
                COALESCE(ou.id,             ru.id)               AS unit_id,
                COALESCE(ou.name,           ru.name)             AS unit_name
            FROM product_par_levels ppl
            JOIN products p      ON ppl.product_id         = p.id
            LEFT JOIN units ru   ON ppl.recommended_unit_id = ru.id
            LEFT JOIN units ou   ON ppl.override_unit_id    = ou.id
            WHERE {where}
            ORDER BY p.name, ppl.day_of_week NULLS FIRST
        """), params).mappings().all()

    return jsonify([dict(r) for r in rows])


@bp.route('/par-levels', methods=['POST'])
@manage_required
def upsert_par_level():
    """Create or update a par level override for a product at a location."""
    data        = request.get_json(force=True)
    product_id  = data.get('product_id')
    location_id = data.get('location_id')
    day_of_week = data.get('day_of_week')  # None = all days baseline
    override_qty     = data.get('override_qty')
    override_unit_id = data.get('override_unit_id')

    if not all([product_id, location_id]):
        return jsonify({'error': 'product_id and location_id are required'}), 400

    try:
        with get_engine().begin() as conn:
            if day_of_week is None:
                # NULL day = default/baseline — use partial index conflict target
                result = conn.execute(text("""
                    INSERT INTO product_par_levels (
                        product_id, location_id, day_of_week,
                        override_qty, override_unit_id,
                        override_by, override_at, notes
                    ) VALUES (
                        :product_id, :location_id, NULL,
                        :override_qty, :override_unit_id,
                        :override_by, NOW(), :notes
                    )
                    ON CONFLICT (product_id, location_id)
                    WHERE day_of_week IS NULL
                    DO UPDATE SET
                        override_qty     = EXCLUDED.override_qty,
                        override_unit_id = EXCLUDED.override_unit_id,
                        override_by      = EXCLUDED.override_by,
                        override_at      = NOW(),
                        notes            = EXCLUDED.notes,
                        updated_at       = NOW()
                    RETURNING id
                """), {
                    'product_id':       product_id,
                    'location_id':      location_id,
                    'override_qty':     override_qty,
                    'override_unit_id': override_unit_id,
                    'override_by':      g.user.get('email'),
                    'notes':            data.get('notes'),
                })
            else:
                # Specific day — use day index conflict target
                result = conn.execute(text("""
                    INSERT INTO product_par_levels (
                        product_id, location_id, day_of_week,
                        override_qty, override_unit_id,
                        override_by, override_at, notes
                    ) VALUES (
                        :product_id, :location_id, :day_of_week,
                        :override_qty, :override_unit_id,
                        :override_by, NOW(), :notes
                    )
                    ON CONFLICT (product_id, location_id, day_of_week)
                    WHERE day_of_week IS NOT NULL
                    DO UPDATE SET
                        override_qty     = EXCLUDED.override_qty,
                        override_unit_id = EXCLUDED.override_unit_id,
                        override_by      = EXCLUDED.override_by,
                        override_at      = NOW(),
                        notes            = EXCLUDED.notes,
                        updated_at       = NOW()
                    RETURNING id
                """), {
                    'product_id':       product_id,
                    'location_id':      location_id,
                    'day_of_week':      day_of_week,
                    'override_qty':     override_qty,
                    'override_unit_id': override_unit_id,
                    'override_by':      g.user.get('email'),
                    'notes':            data.get('notes'),
                })
            par_id = result.fetchone().id
        return jsonify({'id': par_id}), 201
    except Exception as e:
        logger.error(f'upsert_par_level: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/par-levels/<int:par_id>/clear-override', methods=['POST'])
@manage_required
def clear_par_override(par_id):
    """Clear user override — falls back to model recommended par."""
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE product_par_levels SET
                    override_qty     = NULL,
                    override_unit_id = NULL,
                    override_by      = NULL,
                    override_at      = NULL,
                    updated_at       = NOW()
                WHERE id = :id
            """), {'id': par_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'clear_par_override: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Purchase Orders
# =============================================================================

@bp.route('/purchase-orders', methods=['GET'])
@staff_required
def list_purchase_orders():
    """
    List purchase orders — filtered by role:
    - admin: all orders
    - gm/store: their location's orders
    - commissary/comm_gm: commissary orders only
    """
    roles        = g.user.get('roles', [])
    is_admin     = ADMIN in roles
    is_gm        = GM in roles
    is_store     = STORE in roles
    is_comm_user = any(r in roles for r in [COMMISSARY, COMM_GM])

    location_id  = request.args.get('location_id')
    vendor_id    = request.args.get('vendor_id', type=int)
    status       = request.args.get('status')
    is_comm      = request.args.get('is_commissary')
    page         = request.args.get('page', 1, type=int)
    per_page     = request.args.get('per_page', 20, type=int)
    offset       = (page - 1) * per_page

    with get_engine().connect() as conn:
        if not is_admin and (is_gm or is_store):
            location_id = _get_user_location(conn)

    filters = []
    params  = {'limit': per_page, 'offset': offset}

    # Commissary users only see commissary orders
    if is_comm_user and not is_admin:
        filters.append('po.is_commissary = TRUE')

    if location_id:
        filters.append('po.location_id = :location_id')
        params['location_id'] = location_id
    if vendor_id:
        filters.append('po.vendor_id = :vendor_id')
        params['vendor_id'] = vendor_id
    if status:
        filters.append('po.status = :status')
        params['status'] = status
    if is_comm == 'true':
        filters.append('po.is_commissary = TRUE')
    elif is_comm == 'false':
        filters.append('po.is_commissary = FALSE')

    where = ('WHERE ' + ' AND '.join(filters)) if filters else ''

    with get_engine().connect() as conn:
        total = conn.execute(text(f"""
            SELECT COUNT(*) FROM purchase_orders po {where}
        """), params).scalar()

        rows = conn.execute(text(f"""
            SELECT
                po.id, po.location_id, po.order_date,
                po.status, po.is_commissary,
                po.created_by, po.submitted_at, po.received_at,
                po.created_at, po.notes,
                v.id   AS vendor_id,
                v.name AS vendor_name,
                l.location_name,
                COUNT(poi.id) AS line_item_count
            FROM purchase_orders po
            JOIN vendors v    ON po.vendor_id      = v.id
            LEFT JOIN locations l  ON l.store_guid::text = po.location_id
            LEFT JOIN purchase_order_items poi ON poi.purchase_order_id = po.id
            {where}
            GROUP BY po.id, v.id, v.name, l.location_name
            ORDER BY po.order_date DESC, po.created_at DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return jsonify({
        'total':   total,
        'page':    page,
        'per_page': per_page,
        'pages':   max(1, (total + per_page - 1) // per_page),
        'orders':  [dict(r) for r in rows],
    })


@bp.route('/purchase-orders/<int:po_id>', methods=['GET'])
@staff_required
def get_purchase_order(po_id):
    """Get purchase order detail with line items."""
    with get_engine().connect() as conn:
        po = conn.execute(text("""
            SELECT
                po.id, po.location_id, po.order_date, po.expected_date,
                po.status, po.is_commissary, po.notes,
                po.created_by, po.submitted_at, po.received_at,
                po.created_at, po.updated_at,
                v.id   AS vendor_id,
                v.name AS vendor_name,
                l.location_name
            FROM purchase_orders po
            JOIN vendors v   ON po.vendor_id      = v.id
            LEFT JOIN locations l ON l.store_guid::text = po.location_id
            WHERE po.id = :id
        """), {'id': po_id}).mappings().fetchone()

        if not po:
            return jsonify({'error': 'Order not found'}), 404

        items = conn.execute(text("""
            SELECT
                poi.id,
                poi.product_id,
                poi.vendor_item_id,
                poi.vendor_code,
                poi.product_name,
                poi.order_quantity,
                poi.original_quantity,
                poi.base_quantity,
                poi.base_unit_id,
                poi.is_short,
                poi.edited_by,
                poi.edited_at,
                poi.notes,
                poi.comm_section_id,
                u.name  AS order_unit,
                u.id    AS order_unit_id,
                cs.name AS section_name,
                cs.sort_order AS section_sort
            FROM purchase_order_items poi
            LEFT JOIN units u             ON poi.order_unit_id   = u.id
            LEFT JOIN comm_order_sections cs ON poi.comm_section_id = cs.id
            WHERE poi.purchase_order_id = :id
            ORDER BY cs.sort_order NULLS LAST, cs.name NULLS LAST, poi.product_name
        """), {'id': po_id}).mappings().all()

        sections = conn.execute(text("""
            SELECT id, name, sort_order
            FROM comm_order_sections
            WHERE purchase_order_id = :id
            ORDER BY sort_order
        """), {'id': po_id}).mappings().all()

    result = dict(po)
    result['items']    = [dict(i) for i in items]
    result['sections'] = [dict(s) for s in sections]
    return jsonify(result)


@bp.route('/purchase-orders/<int:po_id>', methods=['DELETE'])
@admin_required
def delete_purchase_order(po_id):
    """Delete a purchase order and all its line items. Admin only."""
    try:
        with get_engine().begin() as conn:
            # CASCADE handles purchase_order_items
            conn.execute(text("""
                DELETE FROM purchase_orders WHERE id = :id
            """), {'id': po_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_purchase_order: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-orders/<int:po_id>', methods=['PUT'])
@manage_required
def update_purchase_order(po_id):
    """Update order status or notes."""
    data = request.get_json(force=True)
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE purchase_orders SET
                    status        = COALESCE(:status, status),
                    notes         = :notes,
                    expected_date = COALESCE(:expected_date, expected_date),
                    submitted_at  = CASE WHEN :status = 'submitted' AND submitted_at IS NULL
                                         THEN NOW() ELSE submitted_at END,
                    received_at   = CASE WHEN :status = 'received' AND received_at IS NULL
                                         THEN NOW() ELSE received_at END,
                    updated_at    = NOW()
                WHERE id = :id
            """), {
                'id':            po_id,
                'status':        data.get('status'),
                'notes':         data.get('notes'),
                'expected_date': data.get('expected_date'),
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'update_purchase_order: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-orders/<int:po_id>/items', methods=['POST'])
@manage_required
def add_order_item(po_id):
    """
    Add a product to an existing draft PO.
    - Resolves vendor item from location_vendor_items (falls back to global active)
    - For commissary POs, looks up comm template to assign correct section
    - Creates 'Other' section if product not found in template
    """
    data       = request.get_json(force=True)
    product_id = data.get('product_id')
    quantity   = data.get('order_quantity', 0)
    unit_id    = data.get('unit_id')  # optional override

    if not product_id:
        return jsonify({'error': 'product_id is required'}), 400

    try:
        with get_engine().begin() as conn:
            # Get PO info
            po = conn.execute(text("""
                SELECT po.id, po.location_id, po.vendor_id, po.is_commissary, po.status
                FROM purchase_orders po
                WHERE po.id = :id
            """), {'id': po_id}).fetchone()

            if not po:
                return jsonify({'error': 'Order not found'}), 404
            if po.status != 'draft':
                return jsonify({'error': 'Can only add items to draft orders'}), 400

            # Resolve vendor item
            vendor_item = conn.execute(text("""
                SELECT
                    COALESCE(lvi_vi.id,            vi_g.id)            AS vendor_item_id,
                    COALESCE(lvi_vi.vendor_code,   vi_g.vendor_code)   AS vendor_code,
                    COALESCE(lvi_vi.order_unit_id, vi_g.order_unit_id) AS order_unit_id,
                    COALESCE(lvi_vi.price,         vi_g.price)         AS price,
                    p.name      AS product_name,
                    p.base_unit_id
                FROM products p
                LEFT JOIN location_vendor_items lvi
                    ON lvi.product_id = p.id AND lvi.location_id = :location_id
                LEFT JOIN vendor_items lvi_vi ON lvi.vendor_item_id = lvi_vi.id
                LEFT JOIN vendor_items vi_g
                    ON vi_g.product_id = p.id AND vi_g.active = TRUE
                WHERE p.id = :product_id
            """), {
                'product_id':  product_id,
                'location_id': po.location_id,
            }).fetchone()

            if not vendor_item:
                return jsonify({'error': 'Product not found'}), 404

            # Resolve comm section if commissary order
            comm_section_id = None
            if po.is_commissary:
                # Look up template for this location+vendor
                template = conn.execute(text("""
                    SELECT ct.id FROM comm_order_templates ct
                    WHERE ct.location_id = :location_id
                    AND ct.vendor_id     = :vendor_id
                    AND ct.active        = TRUE
                    LIMIT 1
                """), {
                    'location_id': po.location_id,
                    'vendor_id':   po.vendor_id,
                }).fetchone()

                if template:
                    # Find which section this product belongs to
                    section_row = conn.execute(text("""
                        SELECT s.name, s.sort_order
                        FROM comm_order_template_items i
                        JOIN comm_order_template_sections s ON i.section_id = s.id
                        WHERE s.template_id = :template_id
                        AND i.product_id    = :product_id
                        LIMIT 1
                    """), {
                        'template_id': template.id,
                        'product_id':  product_id,
                    }).fetchone()

                    section_name = section_row.name if section_row else 'Other'
                    section_sort = section_row.sort_order if section_row else 999

                    # Find or create the comm_order_section on this PO
                    existing_section = conn.execute(text("""
                        SELECT id FROM comm_order_sections
                        WHERE purchase_order_id = :po_id AND name = :name
                    """), {'po_id': po_id, 'name': section_name}).fetchone()

                    if existing_section:
                        comm_section_id = existing_section.id
                    else:
                        comm_section_id = conn.execute(text("""
                            INSERT INTO comm_order_sections (purchase_order_id, name, sort_order)
                            VALUES (:po_id, :name, :sort_order)
                            RETURNING id
                        """), {
                            'po_id':      po_id,
                            'name':       section_name,
                            'sort_order': section_sort,
                        }).fetchone().id

            # Use provided unit_id or fall back to vendor item's order unit
            resolved_unit_id = unit_id or vendor_item.order_unit_id

            # Calculate base_quantity
            base_quantity = None
            base_unit_id  = vendor_item.base_unit_id
            if resolved_unit_id and base_unit_id and float(quantity) > 0:
                if resolved_unit_id == base_unit_id:
                    base_quantity = float(quantity)
                else:
                    conv = conn.execute(text("""
                        SELECT conversion, from_unit_id, to_unit_id
                        FROM unit_conversions
                        WHERE (
                            (from_unit_id = :unit_id AND to_unit_id = :base_unit_id)
                            OR
                            (from_unit_id = :base_unit_id AND to_unit_id = :unit_id)
                        )
                        AND (product_id = :product_id OR product_id IS NULL)
                        ORDER BY product_id NULLS LAST,
                                 CASE WHEN from_unit_id = :unit_id THEN 0 ELSE 1 END
                        LIMIT 1
                    """), {
                        'unit_id':      resolved_unit_id,
                        'base_unit_id': base_unit_id,
                        'product_id':   product_id,
                    }).fetchone()
                    if conv:
                        if conv.from_unit_id == resolved_unit_id:
                            base_quantity = float(quantity) * float(conv.conversion)
                        else:
                            base_quantity = float(quantity) / float(conv.conversion)

            # Insert item
            result = conn.execute(text("""
                INSERT INTO purchase_order_items (
                    purchase_order_id, product_id, vendor_item_id,
                    vendor_code, product_name, order_unit_id,
                    order_quantity, original_quantity,
                    base_quantity, base_unit_id,
                    comm_section_id,
                    edited_by, edited_at
                ) VALUES (
                    :po_id, :product_id, :vendor_item_id,
                    :vendor_code, :product_name, :order_unit_id,
                    :order_quantity, :order_quantity,
                    :base_quantity, :base_unit_id,
                    :comm_section_id,
                    :edited_by, NOW()
                )
                ON CONFLICT (purchase_order_id, product_id) DO UPDATE SET
                    order_quantity   = EXCLUDED.order_quantity,
                    original_quantity = EXCLUDED.original_quantity,
                    order_unit_id    = EXCLUDED.order_unit_id,
                    base_quantity    = EXCLUDED.base_quantity,
                    base_unit_id     = EXCLUDED.base_unit_id,
                    comm_section_id  = EXCLUDED.comm_section_id,
                    edited_by        = EXCLUDED.edited_by,
                    edited_at        = NOW()
                RETURNING id
            """), {
                'po_id':           po_id,
                'product_id':      product_id,
                'vendor_item_id':  vendor_item.vendor_item_id,
                'vendor_code':     vendor_item.vendor_code,
                'product_name':    vendor_item.product_name,
                'order_unit_id':   resolved_unit_id,
                'order_quantity':  float(quantity),
                'base_quantity':   base_quantity,
                'base_unit_id':    base_unit_id,
                'comm_section_id': comm_section_id,
                'edited_by':       g.user.get('email'),
            })
            item_id = result.fetchone().id
        return jsonify({'id': item_id}), 201
    except Exception as e:
        logger.error(f'add_order_item: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-order-items/<int:item_id>', methods=['PUT'])
@comm_item_edit_required
def update_order_item(item_id):
    """
    Update a line item.
    - Admin/GM/Commissary GM: can edit quantity, vendor_code, notes, is_short
    - Commissary: can only edit order_quantity and is_short (not vendor_code/notes)
    """
    data    = request.get_json(force=True)
    new_qty = data.get('order_quantity')
    is_comm_only = _has_role(COMMISSARY) and not _has_role(ADMIN, GM, COMM_GM)

    try:
        with get_engine().begin() as conn:
            current = conn.execute(text("""
                SELECT poi.order_quantity, poi.order_unit_id, poi.base_unit_id,
                       poi.product_id
                FROM purchase_order_items poi
                WHERE poi.id = :id
            """), {'id': item_id}).fetchone()

            if not current:
                return jsonify({'error': 'Item not found'}), 404

            # Recalculate base_quantity if qty is changing
            new_base_qty = None
            if new_qty is not None and current.order_unit_id and current.base_unit_id:
                conv = conn.execute(text("""
                    SELECT conversion, from_unit_id, to_unit_id
                    FROM unit_conversions
                    WHERE (
                        (from_unit_id = :order_unit_id AND to_unit_id = :base_unit_id)
                        OR
                        (from_unit_id = :base_unit_id  AND to_unit_id = :order_unit_id)
                    )
                    AND (product_id = :product_id OR product_id IS NULL)
                    ORDER BY product_id NULLS LAST,
                             CASE WHEN from_unit_id = :order_unit_id THEN 0 ELSE 1 END
                    LIMIT 1
                """), {
                    'order_unit_id': current.order_unit_id,
                    'base_unit_id':  current.base_unit_id,
                    'product_id':    current.product_id,
                }).fetchone()

                if conv:
                    factor = float(conv.conversion) if conv.from_unit_id == current.order_unit_id \
                             else 1.0 / float(conv.conversion)
                    new_base_qty = float(new_qty) * factor

            conn.execute(text("""
                UPDATE purchase_order_items SET
                    order_quantity = COALESCE(:order_quantity, order_quantity),
                    base_quantity  = CASE WHEN :new_base_qty IS NOT NULL
                                         THEN :new_base_qty ELSE base_quantity END,
                    is_short       = COALESCE(:is_short, is_short),
                    notes          = CASE WHEN :comm_only THEN notes
                                         ELSE COALESCE(:notes, notes) END,
                    vendor_code    = CASE WHEN :comm_only THEN vendor_code
                                         ELSE COALESCE(:vendor_code, vendor_code) END,
                    edited_by      = CASE
                                        WHEN :order_quantity IS NOT NULL
                                         AND :order_quantity != order_quantity
                                        THEN :edited_by ELSE edited_by END,
                    edited_at      = CASE
                                        WHEN :order_quantity IS NOT NULL
                                         AND :order_quantity != order_quantity
                                        THEN NOW() ELSE edited_at END
                WHERE id = :id
            """), {
                'id':             item_id,
                'order_quantity': float(new_qty) if new_qty is not None else None,
                'new_base_qty':   new_base_qty,
                'is_short':       data.get('is_short'),
                'notes':          data.get('notes'),
                'vendor_code':    data.get('vendor_code'),
                'edited_by':      g.user.get('email'),
                'comm_only':      is_comm_only,
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'update_order_item: {e}')
        return jsonify({'error': str(e)}), 500

    try:
        with get_engine().begin() as conn:
            # Get current item to find unit conversion
            current = conn.execute(text("""
                SELECT poi.order_quantity, poi.order_unit_id, poi.base_unit_id,
                       poi.product_id
                FROM purchase_order_items poi
                WHERE poi.id = :id
            """), {'id': item_id}).fetchone()

            if not current:
                return jsonify({'error': 'Item not found'}), 404

            # Recalculate base_quantity if qty is changing
            new_base_qty = None
            if new_qty is not None and current.order_unit_id and current.base_unit_id:
                conv = conn.execute(text("""
                    SELECT conversion, from_unit_id, to_unit_id
                    FROM unit_conversions
                    WHERE (
                        (from_unit_id = :order_unit_id AND to_unit_id = :base_unit_id)
                        OR
                        (from_unit_id = :base_unit_id  AND to_unit_id = :order_unit_id)
                    )
                    AND (product_id = :product_id OR product_id IS NULL)
                    ORDER BY product_id NULLS LAST,
                             CASE WHEN from_unit_id = :order_unit_id THEN 0 ELSE 1 END
                    LIMIT 1
                """), {
                    'order_unit_id': current.order_unit_id,
                    'base_unit_id':  current.base_unit_id,
                    'product_id':    current.product_id,
                }).fetchone()

                if conv:
                    if conv.from_unit_id == current.order_unit_id:
                        # order unit → base unit directly
                        factor = float(conv.conversion)
                    else:
                        # inverse: base → order, so invert
                        factor = 1.0 / float(conv.conversion)
                    new_base_qty = float(new_qty) * factor

            conn.execute(text("""
                UPDATE purchase_order_items SET
                    order_quantity = COALESCE(:order_quantity, order_quantity),
                    base_quantity  = CASE
                                        WHEN :new_base_qty IS NOT NULL THEN :new_base_qty
                                        ELSE base_quantity
                                     END,
                    notes          = COALESCE(:notes, notes),
                    vendor_code    = COALESCE(:vendor_code, vendor_code),
                    edited_by      = CASE
                                        WHEN :order_quantity IS NOT NULL
                                         AND :order_quantity != order_quantity
                                        THEN :edited_by ELSE edited_by
                                     END,
                    edited_at      = CASE
                                        WHEN :order_quantity IS NOT NULL
                                         AND :order_quantity != order_quantity
                                        THEN NOW() ELSE edited_at
                                     END
                WHERE id = :id
            """), {
                'id':             item_id,
                'order_quantity': float(new_qty) if new_qty is not None else None,
                'new_base_qty':   new_base_qty,
                'notes':          data.get('notes'),
                'vendor_code':    data.get('vendor_code'),
                'edited_by':      g.user.get('email'),
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'update_order_item: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-order-items/<int:item_id>', methods=['DELETE'])
@admin_required
def delete_order_item(item_id):
    """Remove a line item from an order."""
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM purchase_order_items WHERE id = :id
            """), {'id': item_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_order_item: {e}')
        return jsonify({'error': str(e)}), 500


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
