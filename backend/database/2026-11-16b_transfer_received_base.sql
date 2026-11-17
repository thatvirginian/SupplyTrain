-- =============================================================================
-- 2026-11-16b  Transfers: store the received amount in base units
-- =============================================================================
-- RUN THIS BY HAND, AFTER 2026-11-16_transfers_and_unscheduled_orders.sql and
-- BEFORE deploying the code that goes with it (the receive step writes these
-- columns, so receiving fails until they exist).
--
-- Why
--   transfer_items kept the sent amount in base units (base_quantity) but the
--   received amount only in the unit it was sent in (received_quantity).
--   Every amount the system calculates with must be base quantity + base
--   unit, saved at the time it is recorded. Usage needs the received amount.
--
-- What it does
--   1. transfer_items gets received_base_quantity and received_base_unit_id.
--   2. Fills them for transfers ALREADY received, using that line's own sent
--      ratio (base_quantity / quantity), i.e. the conversion in force when the
--      line was saved. From now on the app converts at the time of receiving.
--
-- Safe to run more than once (step 2 only fills rows that are still empty).
-- =============================================================================

BEGIN;

ALTER TABLE public.transfer_items
    ADD COLUMN IF NOT EXISTS received_base_quantity numeric(12,4),
    ADD COLUMN IF NOT EXISTS received_base_unit_id  integer REFERENCES public.units(id);

COMMENT ON COLUMN public.transfer_items.received_base_quantity IS
    'received_quantity converted to the product base unit when the transfer was received. Usage reads this.';
COMMENT ON COLUMN public.transfer_items.received_base_unit_id IS
    'Base unit of received_base_quantity (the product base unit at receive time).';

UPDATE public.transfer_items
SET received_base_quantity = ROUND(received_quantity * base_quantity / quantity, 4),
    received_base_unit_id  = base_unit_id
WHERE received_quantity IS NOT NULL
  AND received_base_quantity IS NULL
  AND base_quantity IS NOT NULL
  AND quantity > 0;

COMMIT;

-- Check: should return 0 (received lines still missing a base amount)
SELECT count(*) AS received_lines_without_base
FROM public.transfer_items
WHERE received_quantity IS NOT NULL AND received_base_quantity IS NULL;
