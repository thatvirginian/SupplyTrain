# =============================================================================
# backend/features/locations/location_routes.py
# =============================================================================
# The list of store locations used by dropdowns and assignment panels (reads the Toast locations table).
#
# Endpoints in this file:
#   GET  /api/locations  list_locations
# =============================================================================

from flask import Blueprint, jsonify
from sqlalchemy import text
import logging

from core.auth import (
    staff_required,
)
from core.database import get_engine

logger = logging.getLogger(__name__)

bp = Blueprint('location_routes', __name__, url_prefix='/api')


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
