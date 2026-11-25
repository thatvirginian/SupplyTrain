-- =============================================================================
-- 2026-11-25b  Storage areas (commissary sub-inventory locations), step 1
-- =============================================================================
-- RUN THIS BY HAND against the app's database, BEFORE deploying the code that
-- goes with it. Nothing in the app runs it for you.
--
-- Why
--   The commissary produces in one place (Main) but keeps stock at other
--   sites too. Step 1 lets every count belong to an AREA of the commissary:
--   production runs and inventories are FOR an area (default Main), and each
--   area keeps its own latest count per product. See storage_areas_plan.md.
--
-- What it does
--   1. storage_areas: the areas of a commissary. Every commissary
--      (locations.is_commissary) gets a "Main" area here.
--   2. production_runs.storage_area_id and inventory_submissions.storage_area_id
--      (NULL = Main, so every existing run / inventory stays Main).
--   3. inventory_area_counts: the day's count per AREA (latest submitted count
--      per product per area per date). The app keeps it up to date.
--   4. Copies the commissaries' existing day's counts (inventory_counts) into
--      inventory_area_counts as Main, so history shows under Main.
--
-- What it does NOT do
--   - It changes no existing row and deletes nothing.
--   - Stores get no areas (they keep working exactly as today).
--   - inventory_counts keeps its meaning for every location; for a commissary
--     with areas it holds the MAIN area's day's count (what it has always held).
--
-- After running it: give each site its opening count (an inventory for that
-- site), before picking from it is added in a later step.
--
-- The code that is live today keeps working after this runs.
-- Safe to run more than once.
-- =============================================================================

BEGIN;

-- 1. Areas -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.storage_areas (
    id           serial PRIMARY KEY,
    location_id  varchar(64)  NOT NULL,
    name         varchar(80)  NOT NULL,
    kind         varchar(8)   NOT NULL DEFAULT 'site',
    restocked    boolean      NOT NULL DEFAULT TRUE,
    notes        text,
    active       boolean      NOT NULL DEFAULT TRUE,
    sort_order   integer      NOT NULL DEFAULT 0,
    created_by   varchar(256),
    created_at   timestamptz  NOT NULL DEFAULT now(),
    updated_at   timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT storage_areas_kind_check CHECK (kind IN ('main', 'site')),
    CONSTRAINT storage_areas_name_check CHECK (length(trim(name)) > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_storage_areas_name
    ON public.storage_areas (location_id, lower(name));
-- exactly one Main per location
CREATE UNIQUE INDEX IF NOT EXISTS idx_storage_areas_one_main
    ON public.storage_areas (location_id) WHERE kind = 'main';

INSERT INTO public.storage_areas (location_id, name, kind, restocked, sort_order, created_by)
SELECT l.store_guid::text, 'Main', 'main', FALSE, 0, 'sql 2026-11-25b'
FROM public.locations l
WHERE l.is_commissary = TRUE
  AND NOT EXISTS (SELECT 1 FROM public.storage_areas a
                  WHERE a.location_id = l.store_guid::text AND a.kind = 'main');

-- 2. Area on production runs and inventories (NULL = Main) -----------------------
ALTER TABLE public.production_runs
    ADD COLUMN IF NOT EXISTS storage_area_id integer REFERENCES public.storage_areas(id);
ALTER TABLE public.inventory_submissions
    ADD COLUMN IF NOT EXISTS storage_area_id integer REFERENCES public.storage_areas(id);
CREATE INDEX IF NOT EXISTS idx_inventory_submissions_area
    ON public.inventory_submissions (storage_area_id) WHERE storage_area_id IS NOT NULL;

-- 3. The day's count per area ----------------------------------------------------
CREATE TABLE IF NOT EXISTS public.inventory_area_counts (
    id                       serial PRIMARY KEY,
    storage_area_id          integer NOT NULL REFERENCES public.storage_areas(id),
    location_id              varchar(64) NOT NULL,
    product_id               bigint  NOT NULL REFERENCES public.products(id),
    count_date               date    NOT NULL,
    base_quantity            numeric(12,4),
    base_unit_id             integer REFERENCES public.units(id),
    entered_quantity         numeric(12,4),
    entered_unit_id          integer REFERENCES public.units(id),
    entered_by               varchar(256),
    inventory_submission_id  integer REFERENCES public.inventory_submissions(id) ON DELETE CASCADE,
    original_quantity        numeric(12,4),
    corrected_by             varchar(256),
    corrected_at             timestamptz,
    correction_notes         text,
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT inventory_area_counts_unique UNIQUE (storage_area_id, product_id, count_date)
);
CREATE INDEX IF NOT EXISTS idx_inventory_area_counts_loc_date
    ON public.inventory_area_counts (location_id, count_date);

-- 4. History: the commissaries' day's counts become Main's -----------------------
INSERT INTO public.inventory_area_counts (
    storage_area_id, location_id, product_id, count_date,
    base_quantity, base_unit_id, entered_quantity, entered_unit_id, entered_by,
    inventory_submission_id, original_quantity, corrected_by, corrected_at, correction_notes
)
SELECT a.id, d.location_id, d.product_id, d.count_date,
       d.base_quantity, d.base_unit_id, d.entered_quantity, d.entered_unit_id, d.entered_by,
       d.inventory_submission_id, d.original_quantity, d.corrected_by, d.corrected_at, d.correction_notes
FROM public.inventory_counts d
JOIN public.storage_areas a ON a.location_id = d.location_id AND a.kind = 'main'
ON CONFLICT (storage_area_id, product_id, count_date) DO NOTHING;

COMMIT;
