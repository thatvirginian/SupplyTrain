-- =============================================================================
-- 2026-11-24  Quality check (QC) weights on production runs
-- =============================================================================
-- RUN THIS BY HAND against the app's database, BEFORE deploying the code that
-- goes with it. Nothing in the app runs it for you.
--
-- Why
--   The commissary pulls bags during production and weighs them (paper sheet:
--   4 "average weight" boxes per product). This records those weights and
--   checks them against a target set by an admin on the product.
--   QC weights are scale readings only: they never change inventory, usage or
--   base units.
--
-- What it does
--   1. product_qc_specs: one row per product an admin set up for QC:
--        enabled, package (the unit that gets weighed, e.g. bag),
--        target weight + tolerance, scale unit ('lb' or 'oz'),
--        package_base_qty = the package's size in base units when the target
--        was set (only to remind "bag size changed since this target was set").
--   2. production_qc_checks: one row per production run + product:
--        the weights as read (up to 4), their average, the result
--        ('ok' / 'low' / 'high' / 'none' = no target), and a COPY of the spec
--        in force when the weights were first saved, so changing a target later
--        never changes past results.
--
-- What it does NOT do
--   - It changes no existing table and deletes nothing.
--
-- The code that is live today keeps working after this runs.
-- Safe to run more than once.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.product_qc_specs (
    product_id        bigint PRIMARY KEY REFERENCES public.products(id) ON DELETE CASCADE,
    enabled           boolean NOT NULL DEFAULT TRUE,
    package_unit_id   integer NOT NULL REFERENCES public.units(id),
    target_weight     numeric(10,3) NOT NULL,
    tolerance         numeric(10,3) NOT NULL DEFAULT 0,
    scale_unit        varchar(8)    NOT NULL DEFAULT 'lb',
    package_base_qty  numeric(14,6),
    notes             text,
    updated_by        varchar(256),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT product_qc_specs_target_check    CHECK (target_weight > 0),
    CONSTRAINT product_qc_specs_tolerance_check CHECK (tolerance >= 0),
    CONSTRAINT product_qc_specs_scale_check     CHECK (scale_unit IN ('lb', 'oz'))
);

CREATE TABLE IF NOT EXISTS public.production_qc_checks (
    id                serial PRIMARY KEY,
    run_id            integer NOT NULL REFERENCES public.production_runs(id) ON DELETE CASCADE,
    product_id        bigint  NOT NULL REFERENCES public.products(id),
    weights           numeric(10,3)[] NOT NULL,
    average_weight    numeric(10,3)   NOT NULL,
    result            varchar(8)      NOT NULL,
    -- the spec in force when the weights were first saved
    package_unit_id   integer REFERENCES public.units(id),
    target_weight     numeric(10,3),
    tolerance         numeric(10,3),
    scale_unit        varchar(8) NOT NULL DEFAULT 'lb',
    entered_by        varchar(256),
    entered_at        timestamptz NOT NULL DEFAULT now(),
    updated_by        varchar(256),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT production_qc_checks_unique       UNIQUE (run_id, product_id),
    CONSTRAINT production_qc_checks_result_check CHECK (result IN ('ok', 'low', 'high', 'none')),
    CONSTRAINT production_qc_checks_scale_check  CHECK (scale_unit IN ('lb', 'oz'))
);
CREATE INDEX IF NOT EXISTS idx_production_qc_checks_product
    ON public.production_qc_checks (product_id);

COMMIT;
