# =============================================================================
# app.py — Inventory & Mapping Application
# =============================================================================
# Flask API backend. All routes return JSON.
# React frontend is served from /frontend/dist after build,
# or proxied from Vite dev server during development.
# =============================================================================

from flask import Flask, jsonify, request, g
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from src.database_setup import get_engine
import base64
import json
import logging
import os
import datetime

class ISODateJSONProvider(DefaultJSONProvider):
    """Serialize date/datetime as ISO 8601 strings instead of RFC 2822."""
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, datetime.date):
            return obj.isoformat()  # → "2026-07-01"
        return super().default(obj)

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.json_provider_class = ISODateJSONProvider
app.json = ISODateJSONProvider(app)
CORS(app, supports_credentials=True)   # Allow React dev server to call Flask

engine = get_engine()
app.config['ENGINE'] = engine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.before_request
def load_user():
    """Decode EasyAuth principal. Falls back to dev user when no headers present."""
    user_id = request.headers.get('X-Ms-Client-Principal-Id')

    if not user_id:
        # Local dev — no EasyAuth headers
        g.user = {
            'user_id':   'dev',
            'username':  'chantilly@anitascorp.com',
            'email':     'chantilly@anitascorp.com',
            'roles':     ['admin'],
            'is_admin':  True,
        }
        return

    roles = []
    principal_encoded = request.headers.get('X-Ms-Client-Principal')
    if principal_encoded:
        try:
            principal = json.loads(base64.b64decode(principal_encoded))
            roles = [
                c['val'] for c in principal.get('claims', [])
                if c.get('typ') == 'roles'
            ]
        except Exception as e:
            logger.warning(f'Failed to decode principal: {e}')

    email = request.headers.get('X-Ms-Client-Principal-Name', '')

    g.user = {
        'user_id':  user_id,
        'username': email,
        'email':    email,
        'roles':    roles,
        'is_admin': 'admin' in roles,
    }


@app.route('/api/auth/me')
def me():
    """Return current user info to React."""
    return jsonify(g.user)


# ── Health check ──────────────────────────────────────────────────────────────

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


# ── Blueprints ────────────────────────────────────────────────────────────────
# Uncomment as each blueprint is built:

from blueprints.products  import bp as products_bp;  app.register_blueprint(products_bp)
from blueprints.sheets import bp as sheets_bp; app.register_blueprint(sheets_bp)
from blueprints.inventory   import bp as inventory_bp; app.register_blueprint(inventory_bp, url_prefix='/api')
# from blueprints.vendors   import bp as vendors_bp;   app.register_blueprint(vendors_bp)
# from blueprints.mapping   import bp as mapping_bp;   app.register_blueprint(mapping_bp)
# from blueprints.inventory import bp as inventory_bp; app.register_blueprint(inventory_bp)
# from blueprints.admin     import bp as admin_bp;     app.register_blueprint(admin_bp)


# ── Serve React in production ─────────────────────────────────────────────────
# In production Flask serves the built React app.
# In development Vite runs separately on port 5173.

import os
from flask import send_from_directory

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), 'frontend', 'dist')

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    """Serve React build in production."""
    if path and os.path.exists(os.path.join(FRONTEND_DIST, path)):
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, 'index.html')


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
