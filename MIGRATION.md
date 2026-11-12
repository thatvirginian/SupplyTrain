# Applying the restructure (Windows)

Nothing here changes behavior, URLs, or the database. Do it on the test bench first.

## 1. Back up
Copy your whole project folder (e.g. to `supplytrain_backup`). You do not use git, so this is your undo.

## 2. Take a "before" snapshot (old layout, optional but recommended)
You already have `before` snapshots from the earlier step; if not:
`python tools\route_snapshot.py --all --out before.txt`

## 3. Copy in the new files
From this package into the project root:
- `backend\`  (whole folder)
- `frontend\src\`  — **delete the old `frontend\src` contents first**, then copy the new `src` in.
  (Keep `frontend\package.json`, `vite.config.js`, `index.html`, `public\` untouched.)
- `Dockerfile`  (replace)
- `PROJECT_MAP.md`  (new)

## 4. Copy your `.env` / local settings
`backend\app.py` is your `app.py` with 3 small edits (dev user is still `admin`).
`.env` can stay in the project root; it is found by walking up from `backend\core\database.py`.

## 5. Delete the old backend (after step 6 passes)
- `app.py` (root), `blueprints\`, root `requirements.txt`, root `tools\`
- **Keep `src\`** until you confirm no other script imports it (for example `orders_pull_Update.py`).
  `src\schema_create.sql` now lives at `backend\database\toast_order_tables.sql`.

## 6. Run and test
```
cd backend
python app.py            # Flask on :5000
```
```
cd frontend
npm run dev              # Vite on :5173
```
Then:
```
python backend\tools\route_snapshot.py --out after.txt
python backend\tools\route_snapshot.py --check-names
python backend\tools\route_snapshot.py --check-imports
```
Expected: 92 routes. Compared with the old snapshot, the only differences are
`delete_inventory_submission` and `correct_inventory_item` using `@gm_or_admin_required`
instead of `@manage_required` (same rule: admin and gm only).

Click through each feature once: Products, Vendor Items, Order Templates, Order Sheets (create, save, submit),
Par Levels, Purchase Orders (accept, ship, fulfill), Commissary Templates, Inventory (count, history, detail),
Inventory Templates, Dashboard, Mapping. Try as `admin`, then `store`.

## 7. Production
The Dockerfile now runs gunicorn from `/app/backend`. `.github/workflows/deploy.yml` needs no change.
