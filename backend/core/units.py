# =============================================================================
# backend/core/units.py
# =============================================================================
# Unit conversion to a product's base unit, shared by every feature that turns
# a counted quantity into base units.
#
# Rule (same as the order sheet save): a unit converts to the product's base
# unit through ONE row in unit_conversions, product-specific first, then
# global, in either direction (a reverse row is used as 1 / conversion).
# The base unit itself always converts with factor 1.
#
#   load_base_units(conn, product_ids)        -> {product_id: base_unit_id}
#   load_conversion_map(conn, product_ids, unit_ids, base_unit_ids) -> conv_map
#   base_factor(conv_map, unit_id, base_unit_id, product_id) -> float | None
#   has_base_conversion(conn, product_id, unit_id) -> bool
# =============================================================================

from sqlalchemy import text


def load_base_units(conn, product_ids):
    """Base unit per product, read from products (never trusted from the client)."""
    if not product_ids:
        return {}
    rows = conn.execute(text("""
        SELECT id, base_unit_id FROM products WHERE id = ANY(:ids)
    """), {'ids': list(product_ids)}).fetchall()
    return {r.id: r.base_unit_id for r in rows}


def load_conversion_map(conn, product_ids, unit_ids, base_unit_ids):
    """
    One query for every conversion that could be needed.
    Returns {(from_unit_id, to_unit_id, product_id_or_None): conversion}.
    """
    if not product_ids or not unit_ids or not base_unit_ids:
        return {}
    rows = conn.execute(text("""
        SELECT from_unit_id, to_unit_id, conversion, product_id
        FROM unit_conversions
        WHERE (from_unit_id = ANY(:unit_ids) OR to_unit_id = ANY(:unit_ids))
        AND   (from_unit_id = ANY(:base_ids) OR to_unit_id = ANY(:base_ids))
        AND   (product_id = ANY(:product_ids) OR product_id IS NULL)
    """), {
        'unit_ids':    list(unit_ids),
        'base_ids':    list(base_unit_ids),
        'product_ids': list(product_ids),
    }).fetchall()
    return {(r.from_unit_id, r.to_unit_id, r.product_id): float(r.conversion) for r in rows}


def base_factor(conv_map, unit_id, base_unit_id, product_id):
    """
    Multiply a quantity in unit_id by this factor to get base units.
    None means there is no conversion (the caller must refuse, never guess).
    """
    if unit_id is None or base_unit_id is None:
        return None
    if unit_id == base_unit_id:
        return 1.0
    for pid in (product_id, None):          # product-specific first, then global
        v = conv_map.get((unit_id, base_unit_id, pid))
        if v:
            return v
        v = conv_map.get((base_unit_id, unit_id, pid))
        if v:
            return 1.0 / v
    return None


def has_base_conversion(conn, product_id, unit_id):
    """True when unit_id can be converted to the product's base unit."""
    base = load_base_units(conn, [product_id]).get(product_id)
    if base is None:
        return False
    conv = load_conversion_map(conn, [product_id], [unit_id], [base])
    return base_factor(conv, unit_id, base, product_id) is not None
