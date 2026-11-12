# =============================================================================
# backend/features/catalog/vendor_item_routes.py
# =============================================================================
# Vendor Items (admin): what each vendor sells, vendor codes, prices; which one is active for a product.
#
# Endpoints in this file:
#   GET   /api/products/<int:product_id>/vendor-items  list_product_vendor_items
#   GET   /api/vendor-items                            list_vendor_items
#   POST  /api/vendor-items                            create_vendor_item
#   POST  /api/vendor-items/<int:item_id>/activate     activate_vendor_item
#   PUT   /api/vendor-items/<int:item_id>              update_vendor_item
# =============================================================================

from flask import Blueprint, jsonify, request
from sqlalchemy import text
import logging

from core.auth import (
    admin_required,
)
from core.database import get_engine

logger = logging.getLogger(__name__)

bp = Blueprint('vendor_item_routes', __name__, url_prefix='/api')


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
