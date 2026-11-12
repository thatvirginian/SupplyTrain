# =============================================================================
# backend/features/par_levels/par_level_routes.py
# =============================================================================
# Par Levels (admin): per-product, per-location, per-day-of-week target quantities, with overrides.
#
# Endpoints in this file:
#   GET   /api/par-levels                              list_par_levels
#   POST  /api/par-levels                              upsert_par_level
#   POST  /api/par-levels/<int:par_id>/clear-override  clear_par_override
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
import logging

from core.auth import (
    manage_required, store_required, _get_user_location,
)
from core.database import get_engine

logger = logging.getLogger(__name__)

bp = Blueprint('par_level_routes', __name__, url_prefix='/api')


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
