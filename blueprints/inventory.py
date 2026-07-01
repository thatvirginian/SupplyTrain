from flask import Blueprint, request, jsonify, g
from sqlalchemy import text
from functools import wraps
from src.database_setup import get_engine
import logging

logger = logging.getLogger(__name__)
bp = Blueprint('inventory', __name__)

# ── Auth ──────────────────────────────────────────────────────────────────────
def _has_role(*roles):
    return any(r in g.user.get('roles', []) for r in roles)

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role('admin'):
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated

def manage_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role('admin', 'gm'):
            return jsonify({'error': 'Manager access required'}), 403
        return f(*args, **kwargs)
    return decorated

def staff_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role('admin', 'gm', 'store', 'commissary', 'commissary_gm'):
            return jsonify({'error': 'Access required'}), 403
        return f(*args, **kwargs)
    return decorated

def _get_user_location(conn):
    email = g.user.get('email', '')
    row = conn.execute(text("""
        SELECT store_guid::text FROM locations WHERE contact_email = :email LIMIT 1
    """), {'email': email}).fetchone()
    if row:
        return row.store_guid
    raise ValueError('Could not determine location')


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
                location_id = _get_user_location(conn)
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
# Inventory Submissions
# =============================================================================

@bp.route('/inventory-submissions', methods=['GET'])
@staff_required
def list_inventory_submissions():
    roles       = g.user.get('roles', [])
    is_admin    = 'admin' in roles
    location_id = request.args.get('location_id')
    source      = request.args.get('source')   # 'count_sheet' | 'manual'
    page        = request.args.get('page', 1, type=int)
    per_page    = request.args.get('per_page', 20, type=int)
    offset      = (page - 1) * per_page

    with get_engine().connect() as conn:
        if not is_admin and not location_id:
            location_id = _get_user_location(conn)

    filters = []
    params  = {'limit': per_page, 'offset': offset}

    if location_id:
        filters.append('ivs.location_id = :location_id')
        params['location_id'] = location_id
    if source:
        filters.append('ivs.source = :source')
        params['source'] = source

    where = ('WHERE ' + ' AND '.join(filters)) if filters else ''

    with get_engine().connect() as conn:
        total = conn.execute(text(f"""
            SELECT COUNT(*) FROM inventory_submissions ivs {where}
        """), params).scalar()

        rows = conn.execute(text(f"""
            SELECT
                ivs.id, ivs.location_id, ivs.count_date,
                ivs.source, ivs.status,
                ivs.submitted_by, ivs.submitted_at,
                ivs.sheet_submission_id,
                ivs.template_id,
                ivs.notes, ivs.created_at,
                l.location_name,
                it.name AS template_name,
                COUNT(ic.id) AS item_count
            FROM inventory_submissions ivs
            LEFT JOIN locations l            ON l.store_guid::text = ivs.location_id
            LEFT JOIN inventory_templates it ON ivs.template_id    = it.id
            LEFT JOIN inventory_counts ic    ON ic.inventory_submission_id = ivs.id
            {where}
            GROUP BY ivs.id, l.location_name, it.name
            ORDER BY ivs.count_date DESC, ivs.created_at DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return jsonify({
        'total':       total,
        'page':        page,
        'per_page':    per_page,
        'pages':       max(1, (total + per_page - 1) // per_page),
        'submissions': [dict(r) for r in rows],
    })


@bp.route('/inventory-submissions/<int:submission_id>', methods=['GET'])
@staff_required
def get_inventory_submission(submission_id):
    with get_engine().connect() as conn:
        sub = conn.execute(text("""
            SELECT
                ivs.id, ivs.location_id, ivs.count_date,
                ivs.source, ivs.status, ivs.notes,
                ivs.submitted_by, ivs.submitted_at,
                ivs.sheet_submission_id, ivs.template_id,
                ivs.created_at, ivs.updated_at,
                l.location_name,
                it.name AS template_name
            FROM inventory_submissions ivs
            LEFT JOIN locations l            ON l.store_guid::text = ivs.location_id
            LEFT JOIN inventory_templates it ON ivs.template_id    = it.id
            WHERE ivs.id = :id
        """), {'id': submission_id}).mappings().fetchone()

        if not sub:
            return jsonify({'error': 'Inventory not found'}), 404

        items = conn.execute(text("""
            SELECT
                ic.id, ic.product_id, ic.count_date,
                ic.base_quantity, ic.base_unit_id,
                ic.entered_quantity, ic.entered_unit_id,
                ic.vendor_code, ic.vendor_id,
                ic.par_qty, ic.par_unit_id, ic.par_base_qty,
                ic.order_qty, ic.order_unit_id,
                ic.original_quantity, ic.corrected_by, ic.corrected_at,
                ic.correction_notes, ic.entered_by,
                p.name      AS product_name,
                c.name      AS category,
                u.name      AS base_unit,
                v.name      AS vendor_name,
                ou.name     AS order_unit,
                pu.name     AS par_unit
            FROM inventory_counts ic
            JOIN products p          ON ic.product_id   = p.id
            LEFT JOIN product_categories c ON p.category_id  = c.id
            LEFT JOIN units u        ON ic.base_unit_id  = u.id
            LEFT JOIN units ou       ON ic.order_unit_id = ou.id
            LEFT JOIN units pu       ON ic.par_unit_id   = pu.id
            LEFT JOIN vendors v      ON ic.vendor_id     = v.id
            WHERE ic.inventory_submission_id = :id
            ORDER BY c.name, p.name
        """), {'id': submission_id}).mappings().all()

        # For manual inventories fetch template sections
        template_sections = []
        if sub['template_id']:
            sections = conn.execute(text("""
                SELECT its.id, its.name, its.sort_order,
                    json_agg(
                        json_build_object(
                            'id',           iti.id,
                            'product_id',   iti.product_id,
                            'product_name', p.name,
                            'base_unit',    u.name,
                            'base_unit_id', p.base_unit_id
                        ) ORDER BY iti.sort_order
                    ) FILTER (WHERE iti.id IS NOT NULL) AS items
                FROM inventory_template_sections its
                LEFT JOIN inventory_template_items iti ON iti.section_id = its.id
                LEFT JOIN products p ON iti.product_id = p.id
                LEFT JOIN units u    ON p.base_unit_id = u.id
                WHERE its.template_id = :template_id
                GROUP BY its.id
                ORDER BY its.sort_order
            """), {'template_id': sub['template_id']}).mappings().all()

            # Fetch count units per item
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

            for s in sections:
                sd = dict(s)
                if sd.get('items'):
                    for item in sd['items']:
                        item['count_units'] = count_units_map.get(item['id'], [])
                template_sections.append(sd)

    result = dict(sub)
    result['items']             = [dict(i) for i in items]
    result['template_sections'] = template_sections
    return jsonify(result)


@bp.route('/inventory-submissions/<int:submission_id>/items/<int:item_id>', methods=['PUT'])
@manage_required
def correct_inventory_item(submission_id, item_id):
    """Admin/GM can correct an inventory count with audit trail."""
    data         = request.get_json(force=True)
    new_quantity = data.get('base_quantity')

    if new_quantity is None:
        return jsonify({'error': 'base_quantity is required'}), 400

    try:
        with get_engine().begin() as conn:
            # Preserve original if first correction
            conn.execute(text("""
                UPDATE inventory_counts SET
                    original_quantity = CASE
                        WHEN original_quantity IS NULL THEN base_quantity
                        ELSE original_quantity
                    END,
                    base_quantity    = :new_quantity,
                    corrected_by     = :corrected_by,
                    corrected_at     = NOW(),
                    correction_notes = :correction_notes
                WHERE id = :id
                AND inventory_submission_id = :submission_id
            """), {
                'id':               item_id,
                'submission_id':    submission_id,
                'new_quantity':     float(new_quantity),
                'corrected_by':     g.user.get('email'),
                'correction_notes': data.get('correction_notes'),
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'correct_inventory_item: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Manual inventory submissions (standalone)
# =============================================================================

@bp.route('/inventory-submissions', methods=['POST'])
@staff_required
def create_inventory_submission():
    """Create a new manual inventory submission."""
    data        = request.get_json(force=True)
    template_id = data.get('template_id')
    count_date  = data.get('count_date')
    location_id = data.get('location_id')

    roles    = g.user.get('roles', [])
    is_admin = 'admin' in roles

    if not count_date:
        return jsonify({'error': 'count_date is required'}), 400
    if not template_id:
        return jsonify({'error': 'template_id is required'}), 400

    try:
        with get_engine().connect() as conn:
            if not is_admin or not location_id:
                location_id = _get_user_location(conn)

        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO inventory_submissions (
                    template_id, location_id, count_date,
                    source, status, submitted_by
                ) VALUES (
                    :template_id, :location_id, :count_date,
                    'manual', 'draft', :submitted_by
                )
                ON CONFLICT DO NOTHING
                RETURNING id
            """), {
                'template_id':  template_id,
                'location_id':  location_id,
                'count_date':   count_date,
                'submitted_by': g.user.get('email'),
            })
            row = result.fetchone()
            if not row:
                # Already exists — return existing
                existing = conn.execute(text("""
                    SELECT id FROM inventory_submissions
                    WHERE template_id = :template_id
                    AND location_id   = :location_id
                    AND count_date    = :count_date
                    AND source        = 'manual'
                """), {
                    'template_id': template_id,
                    'location_id': location_id,
                    'count_date':  count_date,
                }).fetchone()
                return jsonify({'id': existing.id}), 200
        return jsonify({'id': row.id}), 201
    except Exception as e:
        logger.error(f'create_inventory_submission: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-submissions/<int:submission_id>/save', methods=['PUT'])
@staff_required
def save_inventory_entries(submission_id):
    """Save draft inventory entries."""
    data    = request.get_json(force=True)
    entries = data.get('entries', [])

    try:
        with get_engine().begin() as conn:
            sub = conn.execute(text("""
                SELECT status, location_id, count_date FROM inventory_submissions
                WHERE id = :id
            """), {'id': submission_id}).fetchone()

            if not sub:
                return jsonify({'error': 'Inventory not found'}), 404

            for entry in entries:
                product_id   = entry.get('product_id')
                quantity     = entry.get('quantity')
                unit_id      = entry.get('unit_id')
                base_unit_id = entry.get('base_unit_id')

                if not product_id or quantity is None:
                    continue

                # Convert to base quantity
                base_quantity = None
                if unit_id and base_unit_id:
                    if unit_id == base_unit_id:
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
                            'unit_id':     unit_id,
                            'base_unit_id': base_unit_id,
                            'product_id':  product_id,
                        }).fetchone()

                        if conv:
                            if conv.from_unit_id == unit_id:
                                base_quantity = float(quantity) * float(conv.conversion)
                            else:
                                base_quantity = float(quantity) / float(conv.conversion)
                        else:
                            base_quantity = float(quantity)
                else:
                    base_quantity = float(quantity)

                conn.execute(text("""
                    INSERT INTO inventory_counts (
                        inventory_submission_id, location_id, product_id,
                        count_date, base_quantity, base_unit_id,
                        entered_quantity, entered_unit_id, entered_by
                    ) VALUES (
                        :inv_sub_id, :location_id, :product_id,
                        :count_date, :base_quantity, :base_unit_id,
                        :entered_quantity, :entered_unit_id, :entered_by
                    )
                    ON CONFLICT (location_id, product_id, count_date) DO UPDATE SET
                        base_quantity    = EXCLUDED.base_quantity,
                        entered_quantity = EXCLUDED.entered_quantity,
                        entered_unit_id  = EXCLUDED.entered_unit_id,
                        entered_by       = EXCLUDED.entered_by
                """), {
                    'inv_sub_id':      submission_id,
                    'location_id':     sub.location_id,
                    'product_id':      product_id,
                    'count_date':      sub.count_date,
                    'base_quantity':   base_quantity,
                    'base_unit_id':    base_unit_id,
                    'entered_quantity': float(quantity),
                    'entered_unit_id': unit_id,
                    'entered_by':      g.user.get('email'),
                })

        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'save_inventory_entries: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-submissions/<int:submission_id>/submit', methods=['POST'])
@staff_required
def submit_inventory(submission_id):
    """Submit a manual inventory."""
    try:
        with get_engine().begin() as conn:
            sub = conn.execute(text("""
                SELECT status FROM inventory_submissions WHERE id = :id
            """), {'id': submission_id}).fetchone()

            if not sub:
                return jsonify({'error': 'Inventory not found'}), 404
            if sub.status == 'submitted':
                return jsonify({'error': 'Already submitted'}), 400

            conn.execute(text("""
                UPDATE inventory_submissions SET
                    status       = 'submitted',
                    submitted_by = :submitted_by,
                    submitted_at = NOW(),
                    updated_at   = NOW()
                WHERE id = :id
            """), {'id': submission_id, 'submitted_by': g.user.get('email')})

        return jsonify({'status': 'submitted'})
    except Exception as e:
        logger.error(f'submit_inventory: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/inventory-submissions/<int:submission_id>', methods=['DELETE'])
@manage_required
def delete_inventory_submission(submission_id):
    """Delete an inventory submission and its counts."""
    try:
        with get_engine().begin() as conn:
            # Clear inventory_counts link first
            conn.execute(text("""
                UPDATE inventory_counts SET inventory_submission_id = NULL
                WHERE inventory_submission_id = :id
            """), {'id': submission_id})
            conn.execute(text("""
                DELETE FROM inventory_submissions WHERE id = :id
            """), {'id': submission_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_inventory_submission: {e}')
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
