# =============================================================================
# backend/features/commissary/production_qc.py
# =============================================================================
# Quality check (QC) weights: shared rules for the product QC settings
# (catalog/product_qc_routes.py, admin) and the production run sheet
# (production_run_routes.py).
#
# A product set up for QC has a PACKAGE (the unit that gets pulled and weighed,
# e.g. bag), a TARGET weight per package, a TOLERANCE and a SCALE UNIT (lb/oz).
# On a production run, staff enter up to QC_SAMPLES weights per product; the
# average is compared with target ± tolerance -> 'ok' / 'low' / 'high'
# ('none' when there is no target).
#
# QC weights are scale readings only. They never change inventory, usage or
# base units. Each check keeps a copy of the spec in force when its weights were
# first saved, so changing a target later never changes past results.
#
# The spec remembers the package's size in base units when it was saved
# (package_base_qty). If the package's conversion changes afterwards, the spec
# is flagged package_changed ("bag size changed since this target was set").
#
#   QC_SAMPLES
#   load_specs(conn, product_ids)        -> {product_id: spec dict}
#   load_checks(conn, run_id)            -> {product_id: check dict}
#   evaluate(weights, target, tolerance) -> (average, result)
#   package_factor(conn, product_id, unit_id) -> base qty of 1 package, or None
# =============================================================================

from sqlalchemy import text

from core.units import load_base_units, load_conversion_map, base_factor

QC_SAMPLES = 4
SCALE_UNITS = ('lb', 'oz')
_CHANGE_TOLERANCE = 0.005          # 0.5 %: a conversion edit smaller than this is not a "change"


def _f(v):
    return None if v is None else float(v)


def package_factor(conn, product_id, unit_id):
    """How much 1 package is in the product's base unit (today's conversion), or None."""
    base = load_base_units(conn, [product_id]).get(product_id)
    if base is None:
        return None
    conv = load_conversion_map(conn, [product_id], [unit_id], [base])
    return base_factor(conv, unit_id, base, product_id)


def load_specs(conn, product_ids):
    """QC settings per product (enabled or not), with package_changed worked out."""
    product_ids = list(product_ids or [])
    if not product_ids:
        return {}
    rows = conn.execute(text("""
        SELECT s.product_id, s.enabled, s.package_unit_id, u.name AS package_unit,
               s.target_weight, s.tolerance, s.scale_unit, s.package_base_qty,
               s.notes, s.updated_by, s.updated_at, p.base_unit_id, bu.name AS base_unit
        FROM product_qc_specs s
        JOIN products p    ON p.id  = s.product_id
        LEFT JOIN units u  ON u.id  = s.package_unit_id
        LEFT JOIN units bu ON bu.id = p.base_unit_id
        WHERE s.product_id = ANY(:ids)
    """), {'ids': product_ids}).mappings().all()
    if not rows:
        return {}
    conv = load_conversion_map(conn, [r['product_id'] for r in rows],
                               [r['package_unit_id'] for r in rows],
                               [r['base_unit_id'] for r in rows])
    out = {}
    for r in rows:
        now = base_factor(conv, r['package_unit_id'], r['base_unit_id'], r['product_id'])
        then = _f(r['package_base_qty'])
        changed = bool(now and then and abs(now - then) / then > _CHANGE_TOLERANCE)
        out[r['product_id']] = {
            'enabled':            bool(r['enabled']),
            'package_unit_id':    r['package_unit_id'],
            'package_unit':       r['package_unit'],
            'target_weight':      _f(r['target_weight']),
            'tolerance':          _f(r['tolerance']),
            'scale_unit':         r['scale_unit'],
            'package_base_qty':   then,
            'package_base_now':   now,
            'base_unit':          r['base_unit'],
            'package_changed':    changed,
            'package_converts':   now is not None,
            'notes':              r['notes'],
            'updated_by':         r['updated_by'],
            'updated_at':         r['updated_at'],
            'samples':            QC_SAMPLES,
        }
    return out


def load_checks(conn, run_id):
    rows = conn.execute(text("""
        SELECT c.product_id, c.weights, c.average_weight, c.result,
               c.package_unit_id, u.name AS package_unit,
               c.target_weight, c.tolerance, c.scale_unit,
               c.entered_by, c.entered_at, c.updated_by, c.updated_at
        FROM production_qc_checks c
        LEFT JOIN units u ON u.id = c.package_unit_id
        WHERE c.run_id = :id
    """), {'id': run_id}).mappings().all()
    out = {}
    for r in rows:
        d = dict(r)
        d['weights'] = [_f(w) for w in (r['weights'] or [])]
        for k in ('average_weight', 'target_weight', 'tolerance'):
            d[k] = _f(d[k])
        d['spread'] = (round(max(d['weights']) - min(d['weights']), 3)
                       if len(d['weights']) > 1 else 0.0)
        out[r['product_id']] = d
    return out


def evaluate(weights, target, tolerance):
    """(average, result) for the weights against target ± tolerance."""
    avg = round(sum(weights) / len(weights), 3)
    if target is None:
        return avg, 'none'
    tol = tolerance or 0.0
    # A hair of slack so 4.20 against 4.50 ± 0.30 counts as on target.
    if avg < target - tol - 1e-9:
        return avg, 'low'
    if avg > target + tol + 1e-9:
        return avg, 'high'
    return avg, 'ok'
