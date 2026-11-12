# =============================================================================
# backend/features/__init__.py
# =============================================================================
# Each folder in features/ is one feature of the app (it matches the sidebar):
#
#   locations        store locations list (shared dropdown data)
#   catalog          Products, Vendor Items, units, categories, vendors, per-location vendor overrides
#   order_sheets     Order Templates (admin) and Order Sheets (store)
#   par_levels       Par Levels
#   purchase_orders  Order History / Order Detail: accept, ship, receive, fulfill
#   commissary       Comm Templates (and the commissary side of ordering)
#   inventory        Inv Templates (admin) and Inventories (staff)
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
    from features.catalog.product_unit_conversion_routes import bp as product_unit_conversion_routes_bp
    from features.catalog.vendor_item_routes import bp as vendor_item_routes_bp
    from features.catalog.location_vendor_item_routes import bp as location_vendor_item_routes_bp
    from features.order_sheets.order_sheet_template_routes import bp as order_sheet_template_routes_bp
    from features.order_sheets.order_sheet_routes import bp as order_sheet_routes_bp
    from features.par_levels.par_level_routes import bp as par_level_routes_bp
    from features.purchase_orders.purchase_order_routes import bp as purchase_order_routes_bp
    from features.commissary.commissary_template_routes import bp as commissary_template_routes_bp
    from features.inventory.inventory_template_routes import bp as inventory_template_routes_bp
    from features.inventory.inventory_count_routes import bp as inventory_count_routes_bp

    app.register_blueprint(location_routes_bp)
    app.register_blueprint(unit_and_category_routes_bp)
    app.register_blueprint(vendor_routes_bp)
    app.register_blueprint(product_routes_bp)
    app.register_blueprint(product_unit_conversion_routes_bp)
    app.register_blueprint(vendor_item_routes_bp)
    app.register_blueprint(location_vendor_item_routes_bp)
    app.register_blueprint(order_sheet_template_routes_bp)
    app.register_blueprint(order_sheet_routes_bp)
    app.register_blueprint(par_level_routes_bp)
    app.register_blueprint(purchase_order_routes_bp)
    app.register_blueprint(commissary_template_routes_bp)
    app.register_blueprint(inventory_template_routes_bp)
    app.register_blueprint(inventory_count_routes_bp)
