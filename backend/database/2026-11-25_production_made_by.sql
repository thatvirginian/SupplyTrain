-- =============================================================================
-- 2026-11-25  "Made by" per product on production runs
-- =============================================================================
-- RUN THIS BY HAND against the app's database, BEFORE deploying the code that
-- goes with it. Nothing in the app runs it for you.
--
-- Why
--   Like the names written next to each product on the paper production sheet:
--   who made that product on that run (and so pulled and weighed its QC bags).
--   The name is TYPED by whoever fills in the sheet: no PIN, no sign-in, no
--   link to Toast. (Submitting and correcting a run stay signed as before.)
--
-- What it does
--   production_run_made_by: one row per production run + product:
--     made_by     the name as typed
--     entered_by  who saved it (the login, or the signed-in employee)
--
-- What it does NOT do
--   - It changes no existing table and deletes nothing.
--
-- The code that is live today keeps working after this runs.
-- Safe to run more than once.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.production_run_made_by (
    run_id      integer NOT NULL REFERENCES public.production_runs(id) ON DELETE CASCADE,
    product_id  bigint  NOT NULL REFERENCES public.products(id),
    made_by     varchar(80) NOT NULL,
    entered_by  varchar(256),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, product_id),
    CONSTRAINT production_run_made_by_not_blank CHECK (length(trim(made_by)) > 0)
);

COMMIT;
