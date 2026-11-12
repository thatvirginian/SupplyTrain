# SupplyTrain — Project Map

Everything is organized **by feature**. A feature has the same name on the backend and the frontend
(`purchase_orders` is `backend/features/purchase_orders/` and `frontend/src/features/purchase_orders/`).
Code used by every feature lives in `core/` on each side.

## Layout

```
backend/                         Flask API (port 5000 in dev, gunicorn 8000 in prod)
  app.py                         creates the app, registers features, serves frontend/dist
  requirements.txt
  core/
    auth.py                      roles + decorators (admin_required, gm_or_admin_required, ...)
    database.py                  the Postgres engine (get_engine)
  database/
    toast_order_tables.sql       Toast order tables (was src/schema_create.sql)
  features/
    __init__.py                  register_features(app)  <- every route file is listed here
    <feature>/<thing>_routes.py  one file per thing, header lists its endpoints
  tools/route_snapshot.py        refactor safety net (route list + code hashes)

frontend/src/
  main.jsx                       entry
  App.jsx                        routes only (one line per URL)
  core/
    auth/AuthContext.js          AuthContext + useAuth()
    layout/Layout.jsx + .css     sidebar / page shell
    components/NumericInput.jsx
    hooks/useDebounce.js
    utils/dateUtils.js
    styles/                      CSS shared by several features (see below)
  features/<feature>/pages/      <Name>Page.jsx, with its own <Name>Page.css when it has one
```

## Feature map

| Feature (folder) | What it is | Backend files (`backend/features/…`) | Frontend pages (`frontend/src/features/…/pages`) | URLs |
|---|---|---|---|---|
| `catalog` | Products, vendors, vendor items, units, categories | `catalog/unit_and_category_routes.py`, `vendor_routes.py`, `product_routes.py`, `product_unit_conversion_routes.py`, `vendor_item_routes.py`, `location_vendor_item_routes.py` | `ProductListPage`, `ProductDetailPage`, `VendorItemsPage` | `/products`, `/products/:id`, `/vendor-items` |
| `order_sheets` | Admin-made order sheet templates; stores fill in sheets, submitting creates purchase orders + an inventory record | `order_sheets/order_sheet_template_routes.py`, `order_sheet_routes.py` | `OrderTemplateListPage`, `OrderTemplateDetailPage`, `OrderSheetHomePage`, `OrderSheetPage` | `/sheet-templates`, `/sheet-templates/:id`, `/count-sheets`, `/count-sheet/:submissionId` |
| `par_levels` | Par targets per product / location / weekday | `par_levels/par_level_routes.py` | `ParLevelsPage` | `/par-levels` |
| `purchase_orders` | Order lifecycle: open → accepted → shipped → fulfilled (cancelled = admin) | `purchase_orders/purchase_order_routes.py` | `PurchaseOrderHistoryPage`, `PurchaseOrderDetailPage` | `/orders/history`, `/orders/:id` |
| `commissary` | Commissary order templates | `commissary/commissary_template_routes.py` | `CommissaryTemplateListPage`, `CommissaryTemplateDetailPage` | `/comm-order-templates`, `/comm-order-templates/:id` |
| `inventory` | Inventory templates, counts, history, corrections | `inventory/inventory_template_routes.py`, `inventory_count_routes.py` | `InventoryHomePage`, `InventoryHistoryPage`, `InventoryDetailPage`, `InventoryCountSheetPage`, `InventoryTemplateListPage`, `InventoryTemplateDetailPage` | `/inventory`, `/inventory/history`, `/inventory/entry/:submissionId`, `/inventory/:id`, `/inventory-templates`, `/inventory-templates/:id` |
| `locations` | Location list | `locations/location_routes.py` | (none) | |
| `dashboard` | Dashboard (placeholder page, no backend yet) | (none yet) | `DashboardPage` | `/dashboard` |
| `toast_mapping` | Toast item mapping (placeholder page, no backend yet) | (none yet) | `ToastMappingPage` | `/mapping` |

URLs were deliberately **not** renamed (bookmarks and the home-screen icon keep working).

## Shared CSS (`frontend/src/core/styles/`)

| New name | Old name | Used by |
|---|---|---|
| `shared-ui.css` | `catalog.css` | nearly every page (buttons, tables, forms, modals) |
| `template-editor.css` | `sheet-templates.css` | order / commissary / inventory template pages |
| `drag-and-drop.css` | `comm-template.css` | the three template detail pages |
| `count-entry-sheet.css` | `count-sheet.css` | OrderSheetPage, InventoryHomePage, InventoryCountSheetPage |
| `order-and-print.css` | `order-history.css` | purchase-order pages, inventory history/detail |

Page-only CSS sits next to its page (e.g. `PurchaseOrderDetailPage.css`).
`ProductDetailPage.css` and `VendorItemsPage.css` define classes (`.detail-grid`, `.product-search-results`)
that other pages also use; those pages now import them explicitly (marked with a comment).

## Adding things

- **New endpoint in an existing feature:** add it to that feature's `*_routes.py` and update its header list.
- **New feature:** create `backend/features/<name>/` (+ `__init__.py`), add the route file, add one line in
  `backend/features/__init__.py`; create `frontend/src/features/<name>/pages/`, add routes in `App.jsx`.
- **Role checks:** always import from `core/auth.py`; never define a local copy.
