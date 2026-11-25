# =============================================================================
# backend/features/__init__.py
# =============================================================================
# Each folder in features/ is one feature of the app (it matches the sidebar):
#
#   locations        store locations list (shared dropdown data)
#   catalog          Products (+ QC settings), Vendor Items, units, categories, vendors, per-location vendor overrides
#   order_sheets     Order Templates (admin) and Order Sheets (store)
#   par_levels       Par Levels
#   purchase_orders  Order History / Order Detail: accept, ship, receive, fulfill,
#                    plus Unscheduled Orders (catering etc., placed by hand, no inventory)
#   transfers        Store-to-store transfers (open -> sent -> received)
#   usage            Usage Report (count to count, regular = actual - extra orders) + Par Check
#   commissary       Comm Templates (and the commissary side of ordering),
#                    Production Templates, Production (what the commissary made) and
#                    Production Plan (store counts + orders for a delivery day),
#                    Storage Areas (Main + sites) and Commissary Stock
#   inventory        Inv Templates (admin) and Inventories (staff)
#   operators        Employee PINs: Toast employees an admin gave a PIN sign their work on a
#                    shared login (name + PIN, must be clocked in); see core/operators.py
#
# Files are named after what they handle, ending in _routes.py (HTTP endpoints).
# Business logic and PDF builders will live next to them as *_service.py / *_pdf.py.
#
# register_features(app) is the only place blueprints are registered.
# =============================================================================


def register_features(app):
    from features.locations.location_routes import bp as location_routes_bp
    from features.catalog.unit_and_category_routes import bp as unit_and_category_routes_bp
    from features.catalog.vendor_routes import bp as vendor_routes_bp
    from features.catalog.product_routes import bp as product_routes_bp
    from features.catalog.product_qc_routes import bp as product_qc_routes_bp
    from features.catalog.product_unit_conversion_routes import bp as product_unit_conversion_routes_bp
    from features.catalog.vendor_item_routes import bp as vendor_item_routes_bp
    from features.catalog.location_vendor_item_routes import bp as location_vendor_item_routes_bp
    from features.order_sheets.order_sheet_template_routes import bp as order_sheet_template_routes_bp
    from features.order_sheets.order_sheet_routes import bp as order_sheet_routes_bp
    from features.par_levels.par_level_routes import bp as par_level_routes_bp
    from features.purchase_orders.purchase_order_routes import bp as purchase_order_routes_bp
    from features.purchase_orders.unscheduled_order_routes import bp as unscheduled_order_routes_bp
    from features.transfers.transfer_routes import bp as transfer_routes_bp
    from features.usage.usage_routes import bp as usage_routes_bp
    from features.commissary.commissary_template_routes import bp as commissary_template_routes_bp
    from features.commissary.production_template_routes import bp as production_template_routes_bp
    from features.commissary.production_run_routes import bp as production_run_routes_bp
    from features.commissary.storage_area_routes import bp as storage_area_routes_bp
    from features.commissary.production_plan_routes import bp as production_plan_routes_bp
    from features.operators.operator_routes import bp as operator_routes_bp
    from features.inventory.inventory_template_routes import bp as inventory_template_routes_bp
    from features.inventory.inventory_count_routes import bp as inventory_count_routes_bp
    from features.inventory.inventory_daily_routes import bp as inventory_daily_routes_bp

    app.register_blueprint(location_routes_bp)
    app.register_blueprint(unit_and_category_routes_bp)
    app.register_blueprint(vendor_routes_bp)
    app.register_blueprint(product_routes_bp)
    app.register_blueprint(product_qc_routes_bp)
    app.register_blueprint(product_unit_conversion_routes_bp)
    app.register_blueprint(vendor_item_routes_bp)
    app.register_blueprint(location_vendor_item_routes_bp)
    app.register_blueprint(order_sheet_template_routes_bp)
    app.register_blueprint(order_sheet_routes_bp)
    app.register_blueprint(par_level_routes_bp)
    app.register_blueprint(purchase_order_routes_bp)
    app.register_blueprint(unscheduled_order_routes_bp)
    app.register_blueprint(transfer_routes_bp)
    app.register_blueprint(usage_routes_bp)
    app.register_blueprint(commissary_template_routes_bp)
    app.register_blueprint(production_template_routes_bp)
    app.register_blueprint(production_run_routes_bp)
    app.register_blueprint(storage_area_routes_bp)
    app.register_blueprint(production_plan_routes_bp)
    app.register_blueprint(operator_routes_bp)
    app.register_blueprint(inventory_template_routes_bp)
    app.register_blueprint(inventory_count_routes_bp)
    app.register_blueprint(inventory_daily_routes_bp)
