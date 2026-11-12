# =============================================================================
# backend/core/auth.py
# =============================================================================
# WHO may do WHAT: role names, role groups, the permission decorators used on
# every route, and the "which location does this user belong to" lookups.
#
# Roles: admin, gm (store general manager), store, commissary, commissary_gm, readonly
#
# Decorators (use one per route):
#   admin_required           admin only
#   manage_required          admin, gm, commissary_gm
#   gm_or_admin_required     admin, gm                (store-side inventory corrections/deletes)
#   staff_required           admin, gm, store, commissary, commissary_gm
#   store_required           admin, gm, store
#   comm_required            admin, commissary_gm, commissary
#   comm_manage_required     admin, commissary_gm
#   comm_item_edit_required  admin, gm, commissary_gm, commissary, store (route code narrows further)
#   any_role_required        any role including readonly
# =============================================================================

from flask import jsonify, g
from sqlalchemy import text
from functools import wraps


# ── Role constants ────────────────────────────────────────────────────────────

ADMIN        = 'admin'
GM           = 'gm'
STORE        = 'store'
COMMISSARY   = 'commissary'
COMM_GM      = 'commissary_gm'
READONLY     = 'readonly'

ALL_ROLES    = [ADMIN, GM, STORE, COMMISSARY, COMM_GM, READONLY]
STORE_ROLES  = [ADMIN, GM, STORE]                    # store-side access
COMM_ROLES   = [ADMIN, COMM_GM, COMMISSARY]          # commissary-side access
MANAGE_ROLES = [ADMIN, GM, COMM_GM]                  # can edit orders
STAFF_ROLES  = [ADMIN, GM, STORE, COMMISSARY, COMM_GM]  # any active user


def _has_role(*roles):
    """Check if current user has any of the given roles."""
    user_roles = g.user.get('roles', [])
    return any(r in user_roles for r in roles)


def _user_roles():
    return g.user.get('roles', [])


def _is_admin():
    return ADMIN in _user_roles()


def _is_comm():
    """True for commissary or commissary_gm."""
    return any(r in _user_roles() for r in [COMM_GM, COMMISSARY])


# ── Auth decorators ───────────────────────────────────────────────────────────

def admin_required(f):
    """Admin only."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN):
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


def manage_required(f):
    """Admin, GM, or Commissary GM — can edit orders and manage data."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, GM, COMM_GM):
            return jsonify({'error': 'Manager access required'}), 403
        return f(*args, **kwargs)
    return decorated


def staff_required(f):
    """Any authenticated user except readonly."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, GM, STORE, COMMISSARY, COMM_GM):
            return jsonify({'error': 'Access required'}), 403
        return f(*args, **kwargs)
    return decorated


def store_required(f):
    """Admin, GM, or Store — store-side access."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, GM, STORE):
            return jsonify({'error': 'Store access required'}), 403
        return f(*args, **kwargs)
    return decorated


def comm_required(f):
    """Admin, Commissary GM, or Commissary — commissary-side access."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, COMM_GM, COMMISSARY):
            return jsonify({'error': 'Commissary access required'}), 403
        return f(*args, **kwargs)
    return decorated


def comm_manage_required(f):
    """Admin or Commissary GM — can manage commissary templates and orders."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, COMM_GM):
            return jsonify({'error': 'Commissary manager access required'}), 403
        return f(*args, **kwargs)
    return decorated


def comm_item_edit_required(f):
    """
    Admin, GM, Commissary GM, Commissary, or Store can access.
    Business logic inside each route enforces what each role can do.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, GM, COMM_GM, COMMISSARY, STORE):
            return jsonify({'error': 'Access required'}), 403
        return f(*args, **kwargs)
    return decorated


def any_role_required(f):
    """Any role including readonly."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(*ALL_ROLES):
            return jsonify({'error': 'Authentication required'}), 403
        return f(*args, **kwargs)
    return decorated


def _get_user_location(conn):
    """Get location_id for staff user from locations.contact_email."""
    email = g.user.get('email', '')
    row = conn.execute(text("""
        SELECT store_guid FROM locations WHERE contact_email = :email
    """), {'email': email}).fetchone()
    return str(row.store_guid) if row else None


def gm_or_admin_required(f):
    """Admin or store GM only (NOT commissary_gm). Used by inventory corrections and deletes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _has_role(ADMIN, GM):
            return jsonify({'error': 'Manager access required'}), 403
        return f(*args, **kwargs)
    return decorated


def get_user_location_or_raise(conn):
    """Like _get_user_location, but raises ValueError when the user has no location (used by inventory)."""
    email = g.user.get('email', '')
    row = conn.execute(text("""
        SELECT store_guid::text FROM locations WHERE contact_email = :email LIMIT 1
    """), {'email': email}).fetchone()
    if row:
        return row.store_guid
    raise ValueError('Could not determine location')
