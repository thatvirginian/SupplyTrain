# =============================================================================
# backend/features/catalog/product_unit_conversion_routes.py
# =============================================================================
# Product unit conversions (admin): how many base units are in a case, bag, etc.
#
# Endpoints in this file:
#   GET     /api/products/<int:product_id>/units  list_product_units
#   POST    /api/products/<int:product_id>/units  add_product_unit
#   DELETE  /api/unit-conversions/<int:conv_id>   delete_unit_conversion
# =============================================================================

from flask import Blueprint, jsonify, request
from sqlalchemy import text
import logging

from core.auth import (
    admin_required,
)
from core.database import get_engine

logger = logging.getLogger(__name__)

bp = Blueprint('product_unit_conversion_routes', __name__, url_prefix='/api')


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
