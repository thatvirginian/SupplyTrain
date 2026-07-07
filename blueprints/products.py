# =============================================================================
# blueprints/products.py
# =============================================================================
# API routes for product catalog and vendor item management.
#
# Routes:
#   GET    /api/units                         — global units (for dropdowns)
#   GET    /api/categories                    — list all categories
#   POST   /api/categories                    — create category
#   GET    /api/vendors                       — vendor list (for dropdowns)
#   GET    /api/products                      — list products (filterable)
#   GET    /api/products/<id>                 — single product detail
#   POST   /api/products                      — create product (manual)
#   PUT    /api/products/<id>                 — update product
#   GET    /api/products/<id>/vendor-items    — vendor items for a product
#   GET    /api/products/<id>/units           — product unit conversions
#   POST   /api/products/<id>/units           — add unit conversion
#   DELETE /api/unit-conversions/<id>         — delete unit conversion
#   GET    /api/vendor-items                  — all vendor items (filterable)
#   PUT    /api/vendor-items/<id>             — update vendor item
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
from functools import wraps
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('products', __name__, url_prefix='/api')


# ── Auth ──────────────────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin' not in g.user.get('roles', []):
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


def get_engine():
    from flask import current_app
    return current_app.config['ENGINE']


# =============================================================================
# Units — global list for dropdowns
# =============================================================================

@bp.route('/units', methods=['GET'])
@admin_required
def list_units():
    """List all global units for dropdowns."""
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, display, unit_type
            FROM units
            WHERE is_global = TRUE AND active = TRUE
            ORDER BY unit_type, name
        """)).mappings().all()
    return jsonify([dict(r) for r in rows])


# =============================================================================
# Categories
# =============================================================================

@bp.route('/categories', methods=['GET'])
@admin_required
def list_categories():
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, description, sort_order, active
            FROM product_categories
            ORDER BY sort_order, name
        """)).mappings().all()
    return jsonify([dict(r) for r in rows])


@bp.route('/categories', methods=['POST'])
@admin_required
def create_category():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO product_categories (name, description, sort_order)
                VALUES (:name, :description, :sort_order)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    active      = TRUE
                RETURNING id, name, description, sort_order, active
            """), {
                'name':        name,
                'description': data.get('description'),
                'sort_order':  data.get('sort_order', 0),
            })
            row = result.mappings().fetchone()
        return jsonify(dict(row)), 201
    except Exception as e:
        logger.error(f'create_category: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Vendors
# =============================================================================

@bp.route('/vendors', methods=['GET'])
@admin_required
def list_vendors():
    """List all vendors with item counts."""
    is_commissary = request.args.get('is_commissary')

    where = 'WHERE v.active = TRUE'
    params = {}
    if is_commissary == 'true':
        where += ' AND v.is_commissary = TRUE'
    elif is_commissary == 'false':
        where += ' AND v.is_commissary = FALSE'

    with get_engine().connect() as conn:
        rows = conn.execute(text(f"""
            SELECT
                v.id, v.name, v.external_id, v.central_id, v.active, v.is_commissary,
                COUNT(vi.id)                                    AS item_count,
                COUNT(vi.id) FILTER (WHERE vi.active = TRUE)   AS active_item_count
            FROM vendors v
            LEFT JOIN vendor_items vi ON vi.vendor_id = v.id
            {where}
            GROUP BY v.id
            ORDER BY v.name
        """), params).mappings().all()
    return jsonify([dict(r) for r in rows])


# =============================================================================
# Products — list
# =============================================================================

@bp.route('/products', methods=['GET'])
@admin_required
def list_products():
    """
    List products with optional filters.
    Query params:
        category_id  — filter by category
        product_type — filter by type
        active       — true | false (default: true)
        search       — name search
        has_vendor   — true = has vendor items, false = no vendor items
        page         — page number (default: 1)
        per_page     — results per page (default: 50)
    """
    category_id  = request.args.get('category_id', type=int)
    product_type = request.args.get('product_type')
    active       = request.args.get('active', 'true').lower() != 'false'
    search       = request.args.get('search', '').strip()
    has_vendor   = request.args.get('has_vendor')
    page         = request.args.get('page', 1, type=int)
    per_page     = request.args.get('per_page', 50, type=int)
    offset       = (page - 1) * per_page

    filters = ['p.active = :active']
    params  = {'active': active, 'limit': per_page, 'offset': offset}

    if category_id:
        filters.append('p.category_id = :category_id')
        params['category_id'] = category_id

    if product_type:
        filters.append('p.product_type = :product_type')
        params['product_type'] = product_type

    if search:
        filters.append('p.name ILIKE :search')
        params['search'] = f'%{search}%'

    if has_vendor == 'true':
        filters.append('EXISTS (SELECT 1 FROM vendor_items vi WHERE vi.product_id = p.id)')
    elif has_vendor == 'false':
        filters.append('NOT EXISTS (SELECT 1 FROM vendor_items vi WHERE vi.product_id = p.id)')

    where = ' AND '.join(filters)

    with get_engine().connect() as conn:
        total = conn.execute(text(f"""
            SELECT COUNT(*) FROM products p WHERE {where}
        """), params).scalar()

        rows = conn.execute(text(f"""
            SELECT
                p.id,
                p.name,
                p.internal_name,
                p.product_type,
                p.active,
                p.retired_date,
                c.id   AS category_id,
                c.name AS category_name,
                u.name AS base_unit,
                u.id   AS base_unit_id,
                (SELECT COUNT(*) FROM vendor_items vi
                 WHERE vi.product_id = p.id)                              AS vendor_item_count,
                (SELECT COUNT(*) FROM vendor_items vi
                 WHERE vi.product_id = p.id AND vi.active = TRUE)         AS active_vendor_count,
                (SELECT COUNT(*) FROM vendor_items vi
                 WHERE vi.product_id = p.id AND vi.vendor_code IS NOT NULL
                 AND vi.active = TRUE)                                     AS has_vendor_code,
                EXISTS (
                    SELECT 1 FROM recipe_ingredients ri WHERE ri.product_id = p.id
                ) AS used_in_recipe
            FROM products p
            LEFT JOIN product_categories c ON p.category_id = c.id
            LEFT JOIN units u              ON p.base_unit_id = u.id
            WHERE {where}
            ORDER BY c.name NULLS LAST, p.name
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return jsonify({
        'total':    total,
        'page':     page,
        'per_page': per_page,
        'pages':    max(1, (total + per_page - 1) // per_page),
        'products': [dict(r) for r in rows],
    })


# =============================================================================
# Products — single detail
# =============================================================================

@bp.route('/products/<int:product_id>', methods=['GET'])
@admin_required
def get_product(product_id):
    """Full product detail with vendor items, unit conversions, recipe usage."""
    with get_engine().connect() as conn:
        product = conn.execute(text("""
            SELECT
                p.id, p.name, p.internal_name, p.sku,
                p.product_type, p.active, p.retired_date, p.notes,
                p.created_at, p.updated_at,
                p.order_rounding_threshold,
                c.id    AS category_id,
                c.name  AS category_name,
                u.id    AS base_unit_id,
                u.name  AS base_unit,
                u.display AS base_unit_display
            FROM products p
            LEFT JOIN product_categories c ON p.category_id = c.id
            LEFT JOIN units u              ON p.base_unit_id = u.id
            WHERE p.id = :id
        """), {'id': product_id}).mappings().fetchone()

        if not product:
            return jsonify({'error': 'Product not found'}), 404

        vendor_items = conn.execute(text("""
            SELECT
                vi.id, vi.external_id, vi.vendor_code,
                vi.name AS vendor_item_name, vi.packaging,
                vi.order_quantity, vi.price, vi.active,
                vi.retired_date, vi.notes,
                vi.product_id,
                v.id    AS vendor_id,
                v.name  AS vendor_name,
                u.name  AS order_unit,
                u.id    AS order_unit_id
            FROM vendor_items vi
            JOIN vendors v    ON vi.vendor_id     = v.id
            LEFT JOIN units u ON vi.order_unit_id = u.id
            WHERE vi.product_id = :id
            ORDER BY vi.active DESC, v.name
        """), {'id': product_id}).mappings().all()

        unit_convs = conn.execute(text("""
            SELECT
                uc.id, uc.conversion, uc.notes, uc.product_id,
                f.id   AS from_unit_id, f.name AS from_unit,
                t.id   AS to_unit_id,   t.name AS to_unit,
                CASE WHEN uc.product_id IS NULL THEN 'global' ELSE 'product' END AS scope
            FROM unit_conversions uc
            JOIN units f ON uc.from_unit_id = f.id
            JOIN units t ON uc.to_unit_id   = t.id
            WHERE uc.product_id = :id OR uc.product_id IS NULL
            ORDER BY scope DESC, f.name
        """), {'id': product_id}).mappings().all()

        recipes = conn.execute(text("""
            SELECT
                r.id, r.name AS recipe_name,
                ri.quantity,
                u.name AS unit
            FROM recipe_ingredients ri
            JOIN recipes r ON ri.recipe_id = r.id
            LEFT JOIN units u ON ri.unit_id = u.id
            WHERE ri.product_id = :id AND r.active = TRUE
            ORDER BY r.name
        """), {'id': product_id}).mappings().all()

        location_assignments = conn.execute(text("""
            SELECT
                l.store_guid::text  AS location_id,
                l.location_name,
                l.route,
                lvi.id              AS assignment_id,
                lvi.vendor_item_id,
                vi.name             AS vendor_item_name,
                vi.vendor_code,
                vi.active           AS vendor_item_active,
                v.name              AS vendor_name
            FROM locations l
            LEFT JOIN location_vendor_items lvi
                ON lvi.location_id = l.store_guid::text
                AND lvi.product_id = :id
            LEFT JOIN vendor_items vi ON lvi.vendor_item_id = vi.id
            LEFT JOIN vendors v       ON vi.vendor_id       = v.id
            ORDER BY l.location_name
        """), {'id': product_id}).mappings().all()

    result = dict(product)
    result['vendor_items']          = [dict(v) for v in vendor_items]
    result['unit_conversions']      = [dict(u) for u in unit_convs]
    result['used_in_recipes']       = [dict(r) for r in recipes]
    result['location_assignments']  = [dict(l) for l in location_assignments]
    return jsonify(result)


# =============================================================================
# Products — create / update
# =============================================================================

@bp.route('/products', methods=['POST'])
@admin_required
def create_product():
    """Create a new product manually — uses products_manual_id_seq for id."""
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()

    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if not data.get('base_unit_id'):
        return jsonify({'error': 'base_unit_id is required'}), 400

    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO products (
                    id, name, internal_name, sku, product_type,
                    category_id, base_unit_id, active, notes
                ) VALUES (
                    nextval('products_manual_id_seq'),
                    :name, :internal_name, :sku, :product_type,
                    :category_id, :base_unit_id, TRUE, :notes
                )
                RETURNING id
            """), {
                'name':          name,
                'internal_name': data.get('internal_name'),
                'sku':           data.get('sku'),
                'product_type':  data.get('product_type'),
                'category_id':   data.get('category_id'),
                'base_unit_id':  data.get('base_unit_id'),
                'notes':         data.get('notes'),
            })
            product_id = result.fetchone().id
        return jsonify({'id': product_id}), 201
    except Exception as e:
        logger.error(f'create_product: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/products/<int:product_id>', methods=['PUT'])
@admin_required
def update_product(product_id):
    data = request.get_json(force=True)
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE products SET
                    name                     = COALESCE(:name, name),
                    internal_name            = COALESCE(:internal_name, internal_name),
                    sku                      = COALESCE(:sku, sku),
                    product_type             = :product_type,
                    category_id              = :category_id,
                    base_unit_id             = COALESCE(:base_unit_id, base_unit_id),
                    active                   = COALESCE(:active, active),
                    retired_date             = :retired_date,
                    notes                    = :notes,
                    order_rounding_threshold = COALESCE(:order_rounding_threshold, order_rounding_threshold),
                    updated_at               = NOW()
                WHERE id = :id
            """), {
                'id':                       product_id,
                'name':                     data.get('name'),
                'internal_name':            data.get('internal_name'),
                'sku':                      data.get('sku'),
                'product_type':             data.get('product_type'),
                'category_id':              data.get('category_id'),
                'base_unit_id':             data.get('base_unit_id'),
                'active':                   data.get('active'),
                'retired_date':             data.get('retired_date'),
                'notes':                    data.get('notes'),
                'order_rounding_threshold': data.get('order_rounding_threshold'),
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'update_product: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Unit conversions (product-specific)
# =============================================================================

@bp.route('/products/<int:product_id>/units', methods=['GET'])
@admin_required
def list_product_units(product_id):
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT
                uc.id, uc.conversion, uc.notes,
                f.id AS from_unit_id, f.name AS from_unit,
                t.id AS to_unit_id,   t.name AS to_unit
            FROM unit_conversions uc
            JOIN units f ON uc.from_unit_id = f.id
            JOIN units t ON uc.to_unit_id   = t.id
            WHERE uc.product_id = :id
            ORDER BY f.name
        """), {'id': product_id}).mappings().all()
    return jsonify([dict(r) for r in rows])


@bp.route('/products/<int:product_id>/units', methods=['POST'])
@admin_required
def add_product_unit(product_id):
    """
    Add a product-specific unit conversion.
    Accepts from_unit_id (global unit) and conversion factor.
    The to_unit is always the product's base_unit_id.
    """
    data         = request.get_json(force=True)
    from_unit_id = data.get('from_unit_id')
    conversion   = data.get('conversion')

    if not from_unit_id:
        return jsonify({'error': 'from_unit_id is required'}), 400
    if not conversion:
        return jsonify({'error': 'conversion is required'}), 400

    try:
        with get_engine().begin() as conn:
            product = conn.execute(text("""
                SELECT base_unit_id FROM products WHERE id = :id
            """), {'id': product_id}).fetchone()

            if not product:
                return jsonify({'error': 'Product not found'}), 404

            base_unit_id = product.base_unit_id

            # Validate the unit exists
            unit = conn.execute(text("""
                SELECT id FROM units WHERE id = :id
            """), {'id': from_unit_id}).fetchone()

            if not unit:
                return jsonify({'error': 'Unit not found'}), 404

            result = conn.execute(text("""
                INSERT INTO unit_conversions (
                    from_unit_id, to_unit_id, conversion, product_id, notes
                ) VALUES (
                    :from_unit_id, :to_unit_id, :conversion, :product_id, :notes
                )
                ON CONFLICT (from_unit_id, to_unit_id, product_id) DO UPDATE SET
                    conversion = EXCLUDED.conversion,
                    notes      = EXCLUDED.notes,
                    updated_at = NOW()
                RETURNING id
            """), {
                'from_unit_id': from_unit_id,
                'to_unit_id':   base_unit_id,
                'conversion':   conversion,
                'product_id':   product_id,
                'notes':        data.get('notes'),
            })
            conv_id = result.fetchone().id
        return jsonify({'id': conv_id}), 201
    except Exception as e:
        logger.error(f'add_product_unit: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/unit-conversions/<int:conv_id>', methods=['DELETE'])
@admin_required
def delete_unit_conversion(conv_id):
    """Delete a product-specific unit conversion. Cannot delete global conversions."""
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM unit_conversions
                WHERE id = :id AND product_id IS NOT NULL
            """), {'id': conv_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_unit_conversion: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Vendor items
# =============================================================================

@bp.route('/products/<int:product_id>/vendor-items', methods=['GET'])
@admin_required
def list_product_vendor_items(product_id):
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT
                vi.id, vi.external_id, vi.vendor_code,
                vi.name AS vendor_item_name, vi.packaging,
                vi.order_quantity, vi.price, vi.active,
                vi.retired_date, vi.notes,
                v.id   AS vendor_id,
                v.name AS vendor_name,
                u.name AS order_unit,
                u.id   AS order_unit_id
            FROM vendor_items vi
            JOIN vendors v    ON vi.vendor_id     = v.id
            LEFT JOIN units u ON vi.order_unit_id = u.id
            WHERE vi.product_id = :id
            ORDER BY vi.active DESC, v.name
        """), {'id': product_id}).mappings().all()
    return jsonify([dict(r) for r in rows])


@bp.route('/vendor-items', methods=['GET'])
@admin_required
def list_vendor_items():
    """
    List all vendor items with optional filters.
    Query params:
        vendor_id  — filter by vendor
        linked     — true = linked to product, false = unlinked
        has_code   — true = has vendor code, false = no vendor code
        search     — name or vendor code search
        page       — page number (default: 1)
        per_page   — results per page (default: 50)
    """
    vendor_id = request.args.get('vendor_id', type=int)
    linked    = request.args.get('linked')
    has_code  = request.args.get('has_code')
    search    = request.args.get('search', '').strip()
    page      = request.args.get('page', 1, type=int)
    per_page  = request.args.get('per_page', 50, type=int)
    offset    = (page - 1) * per_page

    filters = ['vi.active = TRUE']
    params  = {'limit': per_page, 'offset': offset}

    if vendor_id:
        filters.append('vi.vendor_id = :vendor_id')
        params['vendor_id'] = vendor_id

    if linked == 'true':
        filters.append('vi.product_id IS NOT NULL')
    elif linked == 'false':
        filters.append('vi.product_id IS NULL')

    if has_code == 'true':
        filters.append('vi.vendor_code IS NOT NULL')
    elif has_code == 'false':
        filters.append('vi.vendor_code IS NULL')

    if search:
        filters.append('(vi.name ILIKE :search OR vi.vendor_code ILIKE :search)')
        params['search'] = f'%{search}%'

    where = ' AND '.join(filters)

    with get_engine().connect() as conn:
        total = conn.execute(text(f"""
            SELECT COUNT(*) FROM vendor_items vi WHERE {where}
        """), params).scalar()

        rows = conn.execute(text(f"""
            SELECT
                vi.id, vi.external_id, vi.vendor_code,
                vi.name AS vendor_item_name, vi.packaging,
                vi.order_quantity, vi.price, vi.active, vi.product_id,
                vi.order_unit_id,
                v.id   AS vendor_id,
                v.name AS vendor_name,
                u.name AS order_unit,
                p.name AS product_name,
                c.name AS product_category
            FROM vendor_items vi
            JOIN vendors v              ON vi.vendor_id   = v.id
            LEFT JOIN units u           ON vi.order_unit_id = u.id
            LEFT JOIN products p        ON vi.product_id  = p.id
            LEFT JOIN product_categories c ON p.category_id = c.id
            WHERE {where}
            ORDER BY v.name, vi.name
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return jsonify({
        'total':        total,
        'page':         page,
        'per_page':     per_page,
        'pages':        max(1, (total + per_page - 1) // per_page),
        'vendor_items': [dict(r) for r in rows],
    })


@bp.route('/vendor-items', methods=['POST'])
@admin_required
def create_vendor_item():
    """
    Create a new vendor item and optionally link to a product.
    If product_id provided and no active vendor item exists for that
    product, sets this one active automatically.
    """
    data      = request.get_json(force=True)
    vendor_id = data.get('vendor_id')
    name      = (data.get('name') or '').strip()

    if not vendor_id:
        return jsonify({'error': 'vendor_id is required'}), 400
    if not name:
        return jsonify({'error': 'name is required'}), 400

    product_id = data.get('product_id')

    try:
        with get_engine().begin() as conn:
            # Auto-activate if product has no active vendor item yet
            is_active = False
            if product_id:
                existing = conn.execute(text("""
                    SELECT id FROM vendor_items
                    WHERE product_id = :product_id AND active = TRUE
                    LIMIT 1
                """), {'product_id': product_id}).fetchone()
                is_active = existing is None

            result = conn.execute(text("""
                INSERT INTO vendor_items (
                    vendor_id, vendor_code, name, packaging,
                    order_unit_id, order_quantity, price,
                    product_id, active, notes
                ) VALUES (
                    :vendor_id, :vendor_code, :name, :packaging,
                    :order_unit_id, :order_quantity, :price,
                    :product_id, :active, :notes
                )
                RETURNING id
            """), {
                'vendor_id':      vendor_id,
                'vendor_code':    (data.get('vendor_code') or '').strip() or None,
                'name':           name,
                'packaging':      data.get('packaging'),
                'order_unit_id':  data.get('order_unit_id'),
                'order_quantity': data.get('order_quantity'),
                'price':          data.get('price'),
                'product_id':     product_id,
                'active':         is_active,
                'notes':          data.get('notes'),
            })
            item_id = result.fetchone().id
        return jsonify({'id': item_id, 'active': is_active}), 201
    except Exception as e:
        if 'idx_vendor_items_code_per_vendor' in str(e):
            return jsonify({'error': 'This vendor already has an item with that code.'}), 409
        logger.error(f'create_vendor_item: {e}')
        return jsonify({'error': str(e)}), 500



# =============================================================================
# Location Vendor Items
# =============================================================================

@bp.route('/location-vendor-items', methods=['GET'])
@admin_required
def list_location_vendor_items():
    """
    Get vendor item assignments for a location.
    Query params:
        location_id — required
        product_id  — optional, filter to specific product
    """
    location_id = request.args.get('location_id')
    product_id  = request.args.get('product_id', type=int)

    if not location_id:
        return jsonify({'error': 'location_id is required'}), 400

    filters = ['lvi.location_id = :location_id']
    params  = {'location_id': location_id}

    if product_id:
        filters.append('lvi.product_id = :product_id')
        params['product_id'] = product_id

    where = ' AND '.join(filters)

    with get_engine().connect() as conn:
        rows = conn.execute(text(f"""
            SELECT
                lvi.id,
                lvi.location_id,
                lvi.product_id,
                lvi.vendor_item_id,
                lvi.active,
                lvi.notes,
                p.name      AS product_name,
                p.base_unit_id,
                u.name      AS base_unit,
                vi.name     AS vendor_item_name,
                vi.vendor_code,
                vi.packaging,
                vi.order_unit_id,
                vi.order_quantity,
                vi.price,
                ou.name     AS order_unit,
                v.id        AS vendor_id,
                v.name      AS vendor_name,
                v.is_commissary
            FROM location_vendor_items lvi
            JOIN products p      ON lvi.product_id    = p.id
            JOIN vendor_items vi ON lvi.vendor_item_id = vi.id
            JOIN vendors v       ON vi.vendor_id       = v.id
            LEFT JOIN units u    ON p.base_unit_id     = u.id
            LEFT JOIN units ou   ON vi.order_unit_id   = ou.id
            WHERE {where}
            ORDER BY p.name
        """), params).mappings().all()

    return jsonify([dict(r) for r in rows])


@bp.route('/location-vendor-items', methods=['POST'])
@admin_required
def set_location_vendor_item():
    """
    Set the vendor item for a product at a location.
    Creates or updates the assignment.
    """
    data           = request.get_json(force=True)
    location_id    = data.get('location_id')
    product_id     = data.get('product_id')
    vendor_item_id = data.get('vendor_item_id')

    if not all([location_id, product_id, vendor_item_id]):
        return jsonify({'error': 'location_id, product_id and vendor_item_id are required'}), 400

    try:
        with get_engine().begin() as conn:
            result = conn.execute(text("""
                INSERT INTO location_vendor_items (
                    location_id, product_id, vendor_item_id,
                    active, created_by
                ) VALUES (
                    :location_id, :product_id, :vendor_item_id,
                    TRUE, :created_by
                )
                ON CONFLICT (location_id, product_id) DO UPDATE SET
                    vendor_item_id = EXCLUDED.vendor_item_id,
                    active         = TRUE,
                    updated_at     = NOW()
                RETURNING id
            """), {
                'location_id':    location_id,
                'product_id':     product_id,
                'vendor_item_id': vendor_item_id,
                'created_by':     g.user.get('email'),
            })
            row_id = result.fetchone().id
        return jsonify({'id': row_id}), 201
    except Exception as e:
        logger.error(f'set_location_vendor_item: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/location-vendor-items/<int:item_id>', methods=['DELETE'])
@admin_required
def delete_location_vendor_item(item_id):
    """Remove a vendor item assignment for a location."""
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM location_vendor_items WHERE id = :id
            """), {'id': item_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_location_vendor_item: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/vendor-items/<int:item_id>/activate', methods=['POST'])
@admin_required
def activate_vendor_item(item_id):
    """
    Set a vendor item as the active one for its product.
    Deactivates any currently active vendor item for that product first.
    Atomic — both happen in one transaction.
    """
    try:
        with get_engine().begin() as conn:
            # Get the product_id for this vendor item
            row = conn.execute(text("""
                SELECT product_id FROM vendor_items WHERE id = :id
            """), {'id': item_id}).fetchone()

            if not row:
                return jsonify({'error': 'Vendor item not found'}), 404

            product_id = row.product_id

            if not product_id:
                return jsonify({'error': 'Vendor item is not linked to a product'}), 400

            # Deactivate all other vendor items for this product
            conn.execute(text("""
                UPDATE vendor_items SET
                    active     = FALSE,
                    updated_at = NOW()
                WHERE product_id = :product_id
                AND id != :id
            """), {'product_id': product_id, 'id': item_id})

            # Activate this vendor item
            conn.execute(text("""
                UPDATE vendor_items SET
                    active     = TRUE,
                    updated_at = NOW()
                WHERE id = :id
            """), {'id': item_id})

        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'activate_vendor_item: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/vendor-items/<int:item_id>', methods=['PUT'])
@admin_required
def update_vendor_item(item_id):
    """Update a vendor item — link to product, update pricing, retire."""
    data = request.get_json(force=True)

    def _int_or_none(val):
        try:
            return int(val) if val not in (None, '', 'null') else None
        except (ValueError, TypeError):
            return None

    def _float_or_none(val):
        try:
            return float(val) if val not in (None, '', 'null') else None
        except (ValueError, TypeError):
            return None

    def _str_or_none(val):
        return val.strip() if val and str(val).strip() else None

    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE vendor_items SET
                    product_id     = :product_id,
                    vendor_code    = COALESCE(:vendor_code, vendor_code),
                    packaging      = COALESCE(:packaging, packaging),
                    order_unit_id  = COALESCE(:order_unit_id, order_unit_id),
                    order_quantity = COALESCE(:order_quantity, order_quantity),
                    price          = COALESCE(:price, price),
                    active         = COALESCE(:active, active),
                    retired_date   = :retired_date,
                    notes          = COALESCE(:notes, notes),
                    updated_at     = NOW()
                WHERE id = :id
            """), {
                'id':            item_id,
                'product_id':    _int_or_none(data.get('product_id')),
                'vendor_code':   _str_or_none(data.get('vendor_code')),
                'packaging':     _str_or_none(data.get('packaging')),
                'order_unit_id': _int_or_none(data.get('order_unit_id')),
                'order_quantity':_float_or_none(data.get('order_quantity')),
                'price':         _float_or_none(data.get('price')),
                'active':        data.get('active'),
                'retired_date':  data.get('retired_date') or None,
                'notes':         _str_or_none(data.get('notes')),
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        if 'idx_vendor_items_code_per_vendor' in str(e):
            return jsonify({'error': 'This vendor already has an item with that code.'}), 409
        logger.error(f'update_vendor_item: {e}')
        return jsonify({'error': str(e)}), 500
