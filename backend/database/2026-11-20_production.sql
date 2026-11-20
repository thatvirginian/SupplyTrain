-- =============================================================================
-- 2026-11-20  Commissary production: production templates and production runs
-- =============================================================================
-- RUN THIS BY HAND against the app's database, BEFORE deploying the code that
-- goes with it. Nothing in the app runs it for you.
--
-- Why
--   The commissary records how much of each product it made. Staff fill in a
--   PRODUCTION TEMPLATE (sections of products, each with its production unit);
--   each filled-in sheet is one PRODUCTION RUN. Several runs a day add up.
--
-- What it does
--   1. Makes sure the local foreign table "locations" has is_commissary.
--      The column was added on the Toast-side table; a foreign table only shows
--      the columns it was declared with, so it is declared here too.
--      (IF NOT EXISTS: nothing happens when it is already there.)
--   2. New tables:
--        production_templates            name, notes, active
--        production_template_sections    sections of a template
--        production_template_items       product + its production unit
--        production_template_locations   which commissaries use a template
--        production_runs                 one filled-in sheet (draft / submitted)
--        production_run_items            what one run made, per product:
--                                        as entered + base quantity / base unit,
--                                        plus the correction trail
--
-- What it does NOT do
--   - It changes no existing table except declaring locations.is_commissary.
--   - It deletes nothing.
--
-- The code that is live today keeps working after this runs.
-- Safe to run more than once.
-- =============================================================================

BEGIN;

-- 1. locations.is_commissary on the local foreign table ------------------------
ALTER FOREIGN TABLE public.locations ADD COLUMN IF NOT EXISTS is_commissary boolean;


-- 2. Production templates -------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.production_templates (
    id          serial PRIMARY KEY,
    name        varchar(256) NOT NULL,
    notes       text,
    active      boolean NOT NULL DEFAULT TRUE,
    created_by  varchar(256),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.production_template_sections (
    id           serial PRIMARY KEY,
    template_id  integer NOT NULL REFERENCES public.production_templates(id) ON DELETE CASCADE,
    name         varchar(128) NOT NULL,
    sort_order   integer NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_production_sections_template
    ON public.production_template_sections (template_id);

-- unit_id = the unit this product is produced / entered in on this template.
-- The app only accepts units that convert to the product's base unit.
CREATE TABLE IF NOT EXISTS public.production_template_items (
    id          serial PRIMARY KEY,
    section_id  integer NOT NULL REFERENCES public.production_template_sections(id) ON DELETE CASCADE,
    product_id  bigint  NOT NULL REFERENCES public.products(id),
    unit_id     integer NOT NULL REFERENCES public.units(id),
    sort_order  integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT production_template_items_unique UNIQUE (section_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_production_items_section
    ON public.production_template_items (section_id);

-- location_id is a commissary location (locations.store_guid as text).
CREATE TABLE IF NOT EXISTS public.production_template_locations (
    template_id  integer NOT NULL REFERENCES public.production_templates(id) ON DELETE CASCADE,
    location_id  varchar(64) NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (template_id, location_id)
);


-- 3. Production runs ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.production_runs (
    id               serial PRIMARY KEY,
    template_id      integer REFERENCES public.production_templates(id),
    location_id      varchar(64) NOT NULL,
    production_date  date NOT NULL,
    status           varchar(16) NOT NULL DEFAULT 'draft',
    notes            text,
    created_by       varchar(256),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    submitted_by     varchar(256),
    submitted_at     timestamptz,
    CONSTRAINT production_runs_status_check CHECK (status IN ('draft', 'submitted'))
);
CREATE INDEX IF NOT EXISTS idx_production_runs_location_date
    ON public.production_runs (location_id, production_date);

-- One row per product per run. quantity / unit_id = as entered;
-- base_quantity / base_unit_id = converted at save (base-unit principle).
-- original_quantity = the first submitted value, kept when a submitted run is corrected.
CREATE TABLE IF NOT EXISTS public.production_run_items (
    id                 serial PRIMARY KEY,
    run_id             integer NOT NULL REFERENCES public.production_runs(id) ON DELETE CASCADE,
    product_id         bigint  NOT NULL REFERENCES public.products(id),
    quantity           numeric(12,4) NOT NULL,
    unit_id            integer NOT NULL REFERENCES public.units(id),
    base_quantity      numeric(12,4) NOT NULL,
    base_unit_id       integer NOT NULL REFERENCES public.units(id),
    entered_by         varchar(256),
    entered_at         timestamptz NOT NULL DEFAULT now(),
    original_quantity  numeric(12,4),
    corrected_by       varchar(256),
    corrected_at       timestamptz,
    correction_notes   text,
    CONSTRAINT production_run_items_unique UNIQUE (run_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_production_run_items_product
    ON public.production_run_items (product_id);

COMMIT;
