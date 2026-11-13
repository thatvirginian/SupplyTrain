# =============================================================================
# backend/features/inventory/inventory_count_service.py
# =============================================================================
# The rules for how counts are stored. Used by the inventory routes and by the
# order sheet submit (an order sheet's on-hand creates an inventory).
#
# Three tables, three jobs:
#
#   inventory_count_entries      every line exactly as typed ("2 case", "5 lb"),
#                                per inventory, with history (superseded rows)
#   inventory_submission_counts  what ONE inventory counted per product, in base
#                                units. Order sheet inventories also keep the
#                                par / order / vendor snapshot here.
#   inventory_counts             THE DAY'S COUNT: one row per location / product /
#                                date. Always a copy of the row from the latest
#                                SUBMITTED inventory that counted that product.
#                                This is the table usage is calculated from.
#
# Rules:
#   - Drafts only write inventory_count_entries. Nothing else changes until submit.
#   - Latest submitted inventory wins the day's count, product by product.
#   - Editing an inventory changes its own rows; the day's count changes only if
#     that inventory is the one holding it.
#   - Deleting an inventory hands the day's count back to the next most recent
#     submitted inventory for that day, or removes it when there is none.
#
#   supersede_line_pairs / insert_lines  change single lines, keeping history
#   replace_product_lines(conn, ...)     replace all of one product's lines (corrections)
#   sync_counts_from_entries(conn, ...)  rebuild an inventory's per-product rows from its lines
#   copy_sheet_entries(conn, ...)        copy an order sheet's lines onto its inventory
#   refresh_day_counts(conn, ...)        re-pick the day's count for a location / date
#   adopt_day_counts(conn, ...)          safety net for counts written by the old code
# =============================================================================

from sqlalchemy import text


# Columns copied from the winning inventory's row into the day's count.
_SNAPSHOT_COLS = (
    'base_quantity', 'base_unit_id', 'entered_quantity', 'entered_unit_id', 'entered_by',
    'vendor_item_id', 'vendor_id', 'vendor_code',
    'par_qty', 'par_unit_id', 'par_base_qty', 'order_qty', 'order_unit_id',
    'original_quantity', 'corrected_by', 'corrected_at', 'correction_notes',
)


def supersede_line_pairs(conn, inventory_submission_id, pairs, user):
    """Retire the current line for each (product_id, unit_id) pair. History is kept."""
    if not pairs:
        return
    conn.execute(text("""
        UPDATE inventory_count_entries e
        SET superseded_at = NOW(), superseded_by = :user
        FROM unnest(CAST(:pids AS bigint[]), CAST(:uids AS integer[])) AS m(pid, uid)
        WHERE e.inventory_submission_id = :sid
          AND e.superseded_at IS NULL
          AND e.product_id = m.pid
          AND e.unit_id    = m.uid
    """), {'sid': inventory_submission_id, 'user': user,
           'pids': [p for p, _ in pairs], 'uids': [u for _, u in pairs]})


def insert_lines(conn, inventory_submission_id, rows, user):
    """rows: [{product_id, unit_id, quantity, base_quantity, base_unit_id}]"""
    if not rows:
        return
    conn.execute(text("""
        INSERT INTO inventory_count_entries (
            inventory_submission_id, product_id, unit_id,
            quantity, base_quantity, base_unit_id, entered_by
        ) VALUES (
            :sid, :product_id, :unit_id, :quantity, :base_quantity, :base_unit_id, :user
        )
    """), [dict(r, sid=inventory_submission_id, user=user) for r in rows])


def replace_product_lines(conn, inventory_submission_id, product_id, rows, user):
    """Retire ALL current lines of one product and write these instead (used by corrections)."""
    conn.execute(text("""
        UPDATE inventory_count_entries
        SET superseded_at = NOW(), superseded_by = :user
        WHERE inventory_submission_id = :sid AND product_id = :pid AND superseded_at IS NULL
    """), {'sid': inventory_submission_id, 'pid': product_id, 'user': user})
    insert_lines(conn, inventory_submission_id, rows, user)


def sync_counts_from_entries(conn, inventory_submission_id, user,
                             product_ids=None, mark_changes=True, correction_notes=None):
    """
    Rebuild this inventory's per-product rows (inventory_submission_counts) from
    its current lines: one row per product, all lines added together in base units.

    product_ids=None  -> every product that has lines (used at submit)
    product_ids=[...] -> only these; a product left with no lines loses its row

    mark_changes: when an existing row's total changes, keep the first value in
    original_quantity and record who changed it (the "corrected" trail).

    Order sheet inventories keep their par / order / vendor snapshot: only the
    count columns are touched here.
    """
    if product_ids is not None and not product_ids:
        return
    params = {
        'sid':   inventory_submission_id,
        'user':  user,
        'mark':  bool(mark_changes),
        'notes': correction_notes,
    }
    product_filter = ''
    if product_ids is not None:
        product_filter = 'AND e.product_id = ANY(:pids)'
        params['pids'] = list(product_ids)

    conn.execute(text(f"""
        INSERT INTO inventory_submission_counts (
            inventory_submission_id, product_id,
            base_quantity, base_unit_id,
            entered_quantity, entered_unit_id, entered_by
        )
        SELECT :sid, t.product_id,
               t.base_total, t.base_unit_id,
               CASE WHEN t.line_count = 1 THEN t.one_quantity ELSE t.base_total   END,
               CASE WHEN t.line_count = 1 THEN t.one_unit_id  ELSE t.base_unit_id END,
               t.entered_by
        FROM (
            SELECT e.product_id,
                   SUM(e.base_quantity) AS base_total,
                   MAX(e.base_unit_id)  AS base_unit_id,
                   COUNT(*)             AS line_count,
                   MAX(e.quantity)      AS one_quantity,
                   MAX(e.unit_id)       AS one_unit_id,
                   (ARRAY_AGG(e.entered_by ORDER BY e.entered_at DESC, e.id DESC))[1] AS entered_by
            FROM inventory_count_entries e
            WHERE e.inventory_submission_id = :sid
              AND e.superseded_at IS NULL
              {product_filter}
            GROUP BY e.product_id
        ) t
        ON CONFLICT (inventory_submission_id, product_id) DO UPDATE SET
            original_quantity = CASE
                WHEN :mark AND inventory_submission_counts.base_quantity IS DISTINCT FROM EXCLUDED.base_quantity
                    THEN COALESCE(inventory_submission_counts.original_quantity,
                                  inventory_submission_counts.base_quantity)
                ELSE inventory_submission_counts.original_quantity END,
            corrected_by = CASE
                WHEN :mark AND inventory_submission_counts.base_quantity IS DISTINCT FROM EXCLUDED.base_quantity
                    THEN :user ELSE inventory_submission_counts.corrected_by END,
            corrected_at = CASE
                WHEN :mark AND inventory_submission_counts.base_quantity IS DISTINCT FROM EXCLUDED.base_quantity
                    THEN NOW() ELSE inventory_submission_counts.corrected_at END,
            correction_notes = CASE
                WHEN :mark AND inventory_submission_counts.base_quantity IS DISTINCT FROM EXCLUDED.base_quantity
                    THEN :notes ELSE inventory_submission_counts.correction_notes END,
            base_quantity    = EXCLUDED.base_quantity,
            base_unit_id     = EXCLUDED.base_unit_id,
            entered_quantity = EXCLUDED.entered_quantity,
            entered_unit_id  = EXCLUDED.entered_unit_id,
            entered_by       = EXCLUDED.entered_by,
            updated_at       = NOW()
    """), params)

    if product_ids is not None:
        # A product whose lines were all cleared is no longer counted by this inventory.
        conn.execute(text("""
            DELETE FROM inventory_submission_counts c
            WHERE c.inventory_submission_id = :sid
              AND c.product_id = ANY(:pids)
              AND NOT EXISTS (
                  SELECT 1 FROM inventory_count_entries e
                  WHERE e.inventory_submission_id = c.inventory_submission_id
                    AND e.product_id = c.product_id
                    AND e.superseded_at IS NULL
              )
        """), {'sid': inventory_submission_id, 'pids': list(product_ids)})


def copy_sheet_entries(conn, inventory_submission_id, sheet_submission_id, user):
    """
    Copy an order sheet's on-hand lines onto the inventory it created, so the
    inventory shows the units that were counted. Lines that could not be
    converted to base units are skipped (they are not part of the on-hand total).
    """
    conn.execute(text("""
        INSERT INTO inventory_count_entries (
            inventory_submission_id, product_id, unit_id,
            quantity, base_quantity, base_unit_id, entered_by
        )
        SELECT :inv_id, se.product_id, se.unit_id,
               se.quantity, se.base_quantity, se.base_unit_id, :user
        FROM sheet_entries se
        WHERE se.submission_id = :sheet_id
          AND se.unit_id       IS NOT NULL
          AND se.quantity      IS NOT NULL AND se.quantity >= 0
          AND se.base_quantity IS NOT NULL
          AND se.base_unit_id  IS NOT NULL
    """), {'inv_id': inventory_submission_id, 'sheet_id': sheet_submission_id, 'user': user})


def adopt_day_counts(conn, location_id, count_date):
    """
    Safety net. Call at the START of anything that changes a day's counts.

    Code from before inventory_submission_counts existed wrote straight to the
    day's count. If such a row is still around (saved between running the phase 2
    SQL and deploying this code), its inventory has no row of its own, and the
    fallback rules would treat that count as if it did not exist. This gives
    the inventory its row. With data written by this code it does nothing.
    """
    cols   = ', '.join(_SNAPSHOT_COLS)
    d_cols = ', '.join(f'd.{c}' for c in _SNAPSHOT_COLS)
    conn.execute(text(f"""
        INSERT INTO inventory_submission_counts (
            inventory_submission_id, product_id, {cols}, created_at
        )
        SELECT d.inventory_submission_id, d.product_id, {d_cols}, d.created_at
        FROM inventory_counts d
        WHERE d.location_id = :location_id
          AND d.count_date  = :count_date
          AND d.inventory_submission_id IS NOT NULL
        ON CONFLICT (inventory_submission_id, product_id) DO NOTHING
    """), {'location_id': str(location_id), 'count_date': count_date})


def refresh_day_counts(conn, location_id, count_date, product_ids=None):
    """
    Re-pick the day's count (inventory_counts) for one location and date.

    For each product the winner is the row from the inventory that was submitted
    last (drafts never count). The day's row becomes a copy of the winner. A
    day's row whose inventory no longer counts that product, with no other
    inventory to fall back to, is removed.

    product_ids limits the work to those products; None means the whole day.
    Rows left behind by inventories deleted before this rule existed
    (inventory_submission_id IS NULL) are never removed here.
    """
    if product_ids is not None and not product_ids:
        return
    params = {'location_id': str(location_id), 'count_date': count_date}
    c_filter = d_filter = ''
    if product_ids is not None:
        params['pids'] = list(product_ids)
        c_filter = 'AND c.product_id = ANY(:pids)'
        d_filter = 'AND d.product_id = ANY(:pids)'

    # 1. Remove day rows that no submitted inventory backs any more.
    conn.execute(text(f"""
        DELETE FROM inventory_counts d
        WHERE d.location_id = :location_id
          AND d.count_date  = :count_date
          AND d.inventory_submission_id IS NOT NULL
          {d_filter}
          AND NOT EXISTS (
              SELECT 1
              FROM inventory_submission_counts c
              JOIN inventory_submissions ivs ON ivs.id = c.inventory_submission_id
              WHERE ivs.location_id = d.location_id
                AND ivs.count_date  = d.count_date
                AND ivs.status      = 'submitted'
                AND c.product_id    = d.product_id
          )
    """), params)

    # 2. Copy each product's winner into the day's count.
    cols        = ', '.join(_SNAPSHOT_COLS)
    w_cols      = ', '.join(f'w.{c}' for c in _SNAPSHOT_COLS)
    update_cols = ',\n                '.join(f'{c} = EXCLUDED.{c}' for c in _SNAPSHOT_COLS)
    conn.execute(text(f"""
        INSERT INTO inventory_counts (
            inventory_submission_id, submission_id,
            location_id, product_id, count_date,
            {cols}
        )
        SELECT w.inventory_submission_id, w.sheet_submission_id,
               CAST(:location_id AS varchar), w.product_id, CAST(:count_date AS date),
               {w_cols}
        FROM (
            SELECT DISTINCT ON (c.product_id)
                   c.*, ivs.sheet_submission_id
            FROM inventory_submission_counts c
            JOIN inventory_submissions ivs ON ivs.id = c.inventory_submission_id
            WHERE ivs.location_id = :location_id
              AND ivs.count_date  = :count_date
              AND ivs.status      = 'submitted'
              {c_filter}
            ORDER BY c.product_id, ivs.submitted_at DESC NULLS LAST, ivs.id DESC
        ) w
        ON CONFLICT (location_id, product_id, count_date) DO UPDATE SET
                inventory_submission_id = EXCLUDED.inventory_submission_id,
                submission_id           = EXCLUDED.submission_id,
                {update_cols}
    """), params)
