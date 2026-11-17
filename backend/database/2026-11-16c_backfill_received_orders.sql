-- =============================================================================
-- 2026-11-16c  Backfill receipts on orders fulfilled before the receiving fix
-- =============================================================================
-- RUN THIS BY HAND, ONCE, after deploying the receiving fixes
-- (update-receiving-fixes: Mark Fulfilled now marks unticked lines received
-- and saves the order's received time).
--
-- Why
--   Usage counts what was received and when. Orders fulfilled BEFORE that fix
--   may have lines nobody ticked, and purchase_orders.received_at was never
--   written. Without this, usage reads those deliveries as never received.
--
-- What it does (fulfilled orders only)
--   1. Lines with no received mark -> 'received', by the person who fulfilled
--      the order, at the time it was fulfilled. (Same rule Mark Fulfilled now
--      applies: an unticked line counts as received in full.)
--   2. purchase_orders.received_at = fulfilled_at where it is empty.
--   Lines marked 'returned' or 'received' are not touched.
--   Open / accepted / shipped / cancelled orders are not touched.
--
-- Safe to run more than once (only fills what is still empty).
-- =============================================================================

BEGIN;

-- Before: how much will change
SELECT
    (SELECT count(*) FROM purchase_order_items poi
       JOIN purchase_orders po ON po.id = poi.purchase_order_id
      WHERE po.status = 'fulfilled' AND poi.received_status IS NULL)      AS lines_to_mark_received,
    (SELECT count(*) FROM purchase_orders
      WHERE status = 'fulfilled' AND received_at IS NULL)                 AS orders_without_received_time;

UPDATE public.purchase_order_items poi
SET received_status = 'received',
    received_by     = po.fulfilled_by,
    received_at     = COALESCE(po.fulfilled_at, po.updated_at)
FROM public.purchase_orders po
WHERE po.id = poi.purchase_order_id
  AND po.status = 'fulfilled'
  AND poi.received_status IS NULL;

UPDATE public.purchase_orders
SET received_at = COALESCE(fulfilled_at, updated_at)
WHERE status = 'fulfilled'
  AND received_at IS NULL;

COMMIT;

-- Check: both should be 0
SELECT
    (SELECT count(*) FROM purchase_order_items poi
       JOIN purchase_orders po ON po.id = poi.purchase_order_id
      WHERE po.status = 'fulfilled' AND poi.received_status IS NULL)      AS unmarked_lines_left,
    (SELECT count(*) FROM purchase_orders
      WHERE status = 'fulfilled' AND received_at IS NULL)                 AS orders_without_received_time_left;
