-- =============================================================================
-- 2026-11-13  Products get an "inventory unit" (the unit inventories are shown in)
-- =============================================================================
-- RUN THIS BY HAND against the app's database, BEFORE deploying the daily
-- inventory code. Nothing in the app runs it for you.
--
-- What it does
--   Adds one column, products.inventory_unit_id. It is only a DISPLAY choice:
--   counts are still stored in base units, and are converted to this unit with
--   today's conversion whenever they are shown.
--
--   Empty (NULL, the default for every product) means: show the product in the
--   unit the store orders it in (the store's vendor item order unit, else the
--   product's active vendor item order unit, else the base unit).
--
-- What it does NOT do
--   It fills in nothing and changes no other column or table. The code that is
--   live today keeps working after this runs. Safe to run more than once.
-- =============================================================================

BEGIN;

ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS inventory_unit_id integer REFERENCES public.units(id);

COMMENT ON COLUMN public.products.inventory_unit_id IS
    'Unit inventories are SHOWN in (display only; counts stay in base units). '
    'NULL = the store''s vendor order unit, else the active vendor item order unit, else the base unit. '
    'Must convert directly to the base unit.';

COMMIT;
