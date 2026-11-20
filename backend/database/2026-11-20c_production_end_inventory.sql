-- =============================================================================
-- 2026-11-20c  Production runs record the commissary's END INVENTORY
-- =============================================================================
-- RUN THIS BY HAND against the app's database, AFTER 2026-11-20_production.sql
-- and BEFORE deploying the code that goes with it.
--
-- Why
--   The paper production sheet has two numbers per product: what was made
--   (PROD) and what is on hand after production (END INV). So staff count once,
--   the End Inv boxes on a production run ARE the commissary's inventory for
--   that day: the run creates an ordinary inventory (source 'production') and
--   submitting the run submits it. It then shows in Inventories / Daily
--   Inventory and follows the usual rule (latest submitted count wins).
--
-- What it does
--   1. inventory_submissions.source may also be 'production'
--      (was: 'count_sheet' or 'manual').
--   2. production_runs.inventory_submission_id: the inventory a run created.
--      Deleting that inventory from the Inventories page just unlinks it.
--
-- What it does NOT do
--   - It changes no existing row and deletes nothing.
--
-- The code that is live today keeps working after this runs.
-- Safe to run more than once.
-- =============================================================================

BEGIN;

ALTER TABLE public.inventory_submissions
    DROP CONSTRAINT IF EXISTS inventory_submissions_source_check;
ALTER TABLE public.inventory_submissions
    ADD CONSTRAINT inventory_submissions_source_check
    CHECK (source IN ('count_sheet', 'manual', 'production'));

ALTER TABLE public.production_runs
    ADD COLUMN IF NOT EXISTS inventory_submission_id integer;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'production_runs_inventory_submission_id_fkey') THEN
        ALTER TABLE public.production_runs
            ADD CONSTRAINT production_runs_inventory_submission_id_fkey
            FOREIGN KEY (inventory_submission_id)
            REFERENCES public.inventory_submissions(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_production_runs_inventory
    ON public.production_runs (inventory_submission_id);

COMMIT;
