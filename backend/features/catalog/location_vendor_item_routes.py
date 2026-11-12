# =============================================================================
# backend/features/catalog/location_vendor_item_routes.py
# =============================================================================
# Per-location vendor overrides (admin): this location orders this product from this vendor item.
#
# Endpoints in this file:
#   GET     /api/location-vendor-items                list_location_vendor_items
#   POST    /api/location-vendor-items                set_location_vendor_item
#   DELETE  /api/location-vendor-items/<int:item_id>  delete_location_vendor_item
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
import logging

from core.auth import (
    admin_required,
)
from core.database import get_engine

logger = logging.getLogger(__name__)

bp = Blueprint('location_vendor_item_routes', __name__, url_prefix='/api')


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
