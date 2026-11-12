# =============================================================================
# backend/features/catalog/product_routes.py
# =============================================================================
# Products (admin): the product catalog. List/search, detail, create, update.
#
# Endpoints in this file:
#   GET   /api/products                   list_products
#   GET   /api/products/<int:product_id>  get_product
#   POST  /api/products                   create_product
#   PUT   /api/products/<int:product_id>  update_product
# =============================================================================

from flask import Blueprint, jsonify, request
from sqlalchemy import text
import logging

from core.auth import (
    admin_required,
)
from core.database import get_engine

logger = logging.getLogger(__name__)

bp = Blueprint('product_routes', __name__, url_prefix='/api')


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
    vendor_id    = request.args.get('vendor_id', type=int)
    location_id  = request.args.get('location_id')
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

    if vendor_id and location_id:
        # Filter by resolved vendor — location-specific first, then global active
        filters.append("""
            EXISTS (
                SELECT 1 FROM vendor_items vi
                LEFT JOIN location_vendor_items lvi
                    ON lvi.product_id   = p.id
                    AND lvi.location_id = :location_id
                LEFT JOIN vendor_items lvi_vi ON lvi.vendor_item_id = lvi_vi.id
                WHERE vi.product_id = p.id
                AND COALESCE(lvi_vi.vendor_id, vi.vendor_id) = :vendor_id
                AND (lvi.vendor_item_id IS NOT NULL OR vi.active = TRUE)
            )
        """)
        params['vendor_id']   = vendor_id
        params['location_id'] = location_id
    elif vendor_id:
        # No location — just filter by global active vendor item
        filters.append("""
            EXISTS (
                SELECT 1 FROM vendor_items vi
                WHERE vi.product_id = p.id
                AND vi.vendor_id    = :vendor_id
                AND vi.active       = TRUE
            )
        """)
        params['vendor_id'] = vendor_id

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
