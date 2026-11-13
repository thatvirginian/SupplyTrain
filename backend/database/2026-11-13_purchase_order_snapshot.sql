-- =============================================================================
-- 2026-11-13  Purchase orders keep par and on hand as the order was made,
--             and store the ordered amount correctly in base units
-- =============================================================================
-- RUN THIS BY HAND against the app's database, BEFORE deploying the code that
-- goes with it. Nothing in the app runs it for you.
--
-- Why
--   A purchase order is one branch of an order sheet; the inventory is the other.
--   Until now the order's Par / On Hand were read back from the inventory, so
--   editing the inventory changed what the order showed. From now on each order
--   line keeps its own copy, taken when the order sheet is submitted.
--
-- What it does
--   1. Adds two columns to purchase_order_items: par_unit_id and on_hand_unit_id.
--      (on_hand and par_level already exist and were never filled in.)
--   2. Fills all four for existing orders, from the order sheet inventory's
--      numbers as they were submitted (the first value, if it was edited since).
--   3. ONE-TIME CORRECTION: order lines made by an order sheet stored the
--      shortfall (par minus on hand) as base_quantity instead of what was
--      ordered. Example: need 35 lb, order 1 case of 40 lb -> stored 35, should
--      be 40. This recalculates base_quantity = order quantity x conversion,
--      using today's conversions, for lines nobody edited by hand (edited lines
--      were already calculated this way). Exact unless a conversion changed
--      since the order was placed.
--      Run this file today (before the deploy and once after). Do not re-run
--      it weeks from now: after a conversion change it would recalculate old
--      orders with the new ratio.
--
-- What it does NOT do
--   - It changes no other table and deletes nothing.
--   - It never overwrites a line that already has its copy.
--
-- The code that is live today keeps working after this runs.
-- Safe to run more than once. Run it once more after the new code is live, to
-- fill in any order created in between.
-- =============================================================================

BEGIN;

ALTER TABLE public.purchase_order_items
    ADD COLUMN IF NOT EXISTS par_unit_id     integer REFERENCES public.units(id),
    ADD COLUMN IF NOT EXISTS on_hand_unit_id integer REFERENCES public.units(id);

COMMENT ON COLUMN public.purchase_order_items.on_hand IS
    'On hand when the order was made, in base units (on_hand_unit_id). Never changes afterwards.';
COMMENT ON COLUMN public.purchase_order_items.on_hand_unit_id IS
    'Unit of on_hand: the product''s base unit when the order was made.';
COMMENT ON COLUMN public.purchase_order_items.par_level IS
    'Par when the order was made, in par_unit_id. Never changes afterwards.';
COMMENT ON COLUMN public.purchase_order_items.par_unit_id IS
    'Unit of par_level.';

-- Existing orders made from an order sheet: that sheet's inventory, as submitted.
WITH src AS (
    SELECT DISTINCT ON (poi.id)
           poi.id AS poi_id,
           COALESCE(c.original_quantity, c.base_quantity) AS on_hand,
           c.base_unit_id, c.par_qty, c.par_unit_id
    FROM public.purchase_order_items poi
    JOIN public.purchase_orders po          ON po.id = poi.purchase_order_id
    JOIN public.inventory_submissions invs  ON invs.source = 'count_sheet'
                                          AND (
                                               (po.sheet_submission_id IS NOT NULL
                                                AND invs.sheet_submission_id = po.sheet_submission_id)
                                            OR (po.sheet_submission_id IS NULL
                                                AND invs.location_id = po.location_id
                                                AND invs.count_date  = po.order_date)
                                          )
    JOIN public.inventory_submission_counts c
                                            ON c.inventory_submission_id = invs.id
                                           AND c.product_id = poi.product_id
    WHERE poi.on_hand IS NULL AND poi.par_level IS NULL
    ORDER BY poi.id, (c.par_qty IS NOT NULL) DESC, invs.id DESC
)
UPDATE public.purchase_order_items poi
SET on_hand         = src.on_hand,
    on_hand_unit_id = src.base_unit_id,
    par_level       = src.par_qty,
    par_unit_id     = src.par_unit_id
FROM src
WHERE poi.id = src.poi_id;

-- 3. Ordered amount in base units, for order lines made by an order sheet
CREATE TEMP TABLE _po_base_fix ON COMMIT DROP AS
SELECT poi.id, poi.base_quantity AS old_base, conv.new_base
FROM public.purchase_order_items poi
JOIN public.purchase_orders po ON po.id = poi.purchase_order_id
JOIN LATERAL (
    SELECT CASE
             WHEN poi.order_unit_id = poi.base_unit_id THEN poi.order_quantity
             WHEN uc.from_unit_id = poi.order_unit_id  THEN poi.order_quantity * uc.conversion
             ELSE poi.order_quantity / uc.conversion
           END AS new_base
    FROM (SELECT 1) one
    LEFT JOIN LATERAL (
        SELECT u.from_unit_id, u.conversion
        FROM public.unit_conversions u
        WHERE ((u.from_unit_id = poi.order_unit_id AND u.to_unit_id = poi.base_unit_id)
            OR (u.from_unit_id = poi.base_unit_id  AND u.to_unit_id = poi.order_unit_id))
          AND (u.product_id = poi.product_id OR u.product_id IS NULL)
          AND u.conversion > 0
        ORDER BY u.product_id NULLS LAST
        LIMIT 1
    ) uc ON TRUE
    WHERE poi.order_unit_id = poi.base_unit_id OR uc.conversion IS NOT NULL
) conv ON TRUE
WHERE po.sheet_submission_id IS NOT NULL
  AND poi.edited_by IS NULL
  AND poi.order_quantity IS NOT NULL
  AND poi.order_unit_id  IS NOT NULL
  AND poi.base_unit_id   IS NOT NULL
  AND ROUND(conv.new_base, 4) IS DISTINCT FROM poi.base_quantity;

UPDATE public.purchase_order_items poi
SET base_quantity = ROUND(f.new_base, 4)
FROM _po_base_fix f
WHERE poi.id = f.id;

SELECT count(*) AS order_lines_base_corrected FROM _po_base_fix;

-- How many order lines have their copy now, and how many could not be filled
-- (for example, lines whose order sheet inventory was deleted).
SELECT count(*) FILTER (WHERE on_hand IS NOT NULL OR par_level IS NOT NULL) AS lines_with_snapshot,
       count(*) FILTER (WHERE on_hand IS NULL AND par_level IS NULL)       AS lines_without
FROM public.purchase_order_items;

COMMIT;
