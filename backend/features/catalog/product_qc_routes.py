# =============================================================================
# backend/features/catalog/product_qc_routes.py
# =============================================================================
# A product's quality check (QC) settings, on the Products page (admin only;
# commissary GMs run the commissary, they do not set targets).
#   Weigh for QC (enabled), package (the unit that is weighed, e.g. bag),
#   target weight per package, tolerance, scale unit (lb / oz).
# The package must convert to the product's base unit (same rule as every
# other unit). Rules for using the settings: features/commissary/production_qc.py.
#
# Endpoints in this file:
#   GET     /api/products/<int:product_id>/qc   get_product_qc
#   PUT     /api/products/<int:product_id>/qc   set_product_qc
#   DELETE  /api/products/<int:product_id>/qc   delete_product_qc
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text

from core.auth import admin_required
from core.database import get_engine
from core.units import load_unit_choices
from features.commissary.production_qc import load_specs, package_factor, SCALE_UNITS, QC_SAMPLES

bp = Blueprint('product_qc_routes', __name__, url_prefix='/api')


def _product_exists(conn, product_id):
    return conn.execute(text("SELECT 1 FROM products WHERE id = :id"),
                        {'id': product_id}).fetchone() is not None


@bp.route('/products/<int:product_id>/qc', methods=['GET'])
@admin_required
def get_product_qc(product_id):
    """The product's QC settings (null when never set up) and the packages it can use."""
    with get_engine().connect() as conn:
        if not _product_exists(conn, product_id):
            return jsonify({'error': 'Product not found'}), 404
        spec = load_specs(conn, [product_id]).get(product_id)
        units = load_unit_choices(conn, [product_id]).get(product_id, [])
    return jsonify({'spec': spec, 'package_choices': units,
                    'scale_units': list(SCALE_UNITS), 'samples': QC_SAMPLES})


@bp.route('/products/<int:product_id>/qc', methods=['PUT'])
@admin_required
def set_product_qc(product_id):
    """
    Body: {enabled, package_unit_id, target_weight, tolerance, scale_unit, notes}
    Saving also records the package's size in base units today, which is how
    a later bag-size change is noticed.
    """
    data = request.get_json(force=True) or {}
    try:
        unit_id   = int(data.get('package_unit_id'))
        target    = round(float(data.get('target_weight')), 3)
        tolerance = round(float(data.get('tolerance') or 0), 3)
    except (TypeError, ValueError):
        return jsonify({'error': 'Package, target weight and tolerance must be filled in with numbers'}), 400
    scale = (data.get('scale_unit') or 'lb').strip().lower()
    if scale not in SCALE_UNITS:
        return jsonify({'error': 'Scale unit must be lb or oz'}), 400
    if target <= 0:
        return jsonify({'error': 'Target weight must be more than 0'}), 400
    if tolerance < 0:
        return jsonify({'error': 'Tolerance cannot be negative'}), 400
    if tolerance >= target:
        return jsonify({'error': 'Tolerance must be smaller than the target weight'}), 400
    enabled = bool(data.get('enabled', True))

    with get_engine().begin() as conn:
        if not _product_exists(conn, product_id):
            return jsonify({'error': 'Product not found'}), 404
        factor = package_factor(conn, product_id, unit_id)
        if factor is None:
            return jsonify({'error': 'This package unit has no conversion to the product\'s base unit. '
                                     'Add the conversion first.'}), 400
        conn.execute(text("""
            INSERT INTO product_qc_specs (
                product_id, enabled, package_unit_id, target_weight, tolerance,
                scale_unit, package_base_qty, notes, updated_by, updated_at
            ) VALUES (:pid, :enabled, :uid, :target, :tol, :scale, :pbq, :notes, :by, NOW())
            ON CONFLICT (product_id) DO UPDATE SET
                enabled          = EXCLUDED.enabled,
                package_unit_id  = EXCLUDED.package_unit_id,
                target_weight    = EXCLUDED.target_weight,
                tolerance        = EXCLUDED.tolerance,
                scale_unit       = EXCLUDED.scale_unit,
                package_base_qty = EXCLUDED.package_base_qty,
                notes            = EXCLUDED.notes,
                updated_by       = EXCLUDED.updated_by,
                updated_at       = NOW()
        """), {'pid': product_id, 'enabled': enabled, 'uid': unit_id, 'target': target,
               'tol': tolerance, 'scale': scale, 'pbq': round(factor, 6),
               'notes': (data.get('notes') or '').strip() or None, 'by': g.user.get('email')})
        spec = load_specs(conn, [product_id]).get(product_id)
    return jsonify({'status': 'ok', 'spec': spec})


@bp.route('/products/<int:product_id>/qc', methods=['DELETE'])
@admin_required
def delete_product_qc(product_id):
    """Remove the settings. Weights already recorded keep their own copy of the spec."""
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM product_qc_specs WHERE product_id = :id"), {'id': product_id})
    return jsonify({'status': 'ok'})
