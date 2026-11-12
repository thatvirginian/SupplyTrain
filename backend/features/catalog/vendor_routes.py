# =============================================================================
# backend/features/catalog/vendor_routes.py
# =============================================================================
# Vendors (dropdown list; can filter to commissary vendors).
#
# Endpoints in this file:
#   GET  /api/vendors  list_vendors
# =============================================================================

from flask import Blueprint, jsonify, request
from sqlalchemy import text
import logging

from core.auth import (
    admin_required,
)
from core.database import get_engine

logger = logging.getLogger(__name__)

bp = Blueprint('vendor_routes', __name__, url_prefix='/api')


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
