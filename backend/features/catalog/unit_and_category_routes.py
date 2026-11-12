# =============================================================================
# backend/features/catalog/unit_and_category_routes.py
# =============================================================================
# Units of measure and product categories (dropdown data).
#
# Endpoints in this file:
#   GET   /api/units       list_units
#   GET   /api/categories  list_categories
#   POST  /api/categories  create_category
# =============================================================================

from flask import Blueprint, jsonify, request
from sqlalchemy import text
import logging

from core.auth import (
    admin_required,
)
from core.database import get_engine

logger = logging.getLogger(__name__)

bp = Blueprint('unit_and_category_routes', __name__, url_prefix='/api')


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
