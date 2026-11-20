# =============================================================================
# backend/features/commissary/commissary_access.py
# =============================================================================
# Which locations are commissaries, and which commissary a request works on.
#
# A commissary is a location with locations.is_commissary = TRUE (the column
# lives on the Toast-side table; the local foreign table declares it, see
# database/2026-11-20_production.sql). Several commissaries are supported.
#
#   list_commissary_locations(conn)                 -> [{store_guid, location_name, abbreviation}]
#   is_commissary_location(conn, location_id)       -> bool
#   resolve_commissary_location(conn, requested_id) -> location_id (str) or raises CommissaryAccessError
# =============================================================================

from sqlalchemy import text

from core.auth import _is_admin, _get_user_location


class CommissaryAccessError(Exception):
    """The user may not work on this commissary. Carries the HTTP status."""
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def list_commissary_locations(conn):
    rows = conn.execute(text("""
        SELECT store_guid::text AS store_guid, location_name, abbreviation
        FROM locations
        WHERE is_commissary = TRUE
        ORDER BY location_name
    """)).mappings().all()
    return [dict(r) for r in rows]


def is_commissary_location(conn, location_id):
    if not location_id:
        return False
    row = conn.execute(text("""
        SELECT 1 FROM locations
        WHERE store_guid::text = :id AND is_commissary = TRUE
    """), {'id': str(location_id)}).fetchone()
    return row is not None


def resolve_commissary_location(conn, requested_id=None, required=True):
    """
    Admins: the commissary they asked for (requested_id); when required and
    missing, refuse. Everyone else: their own location (login email), which
    must be a commissary; a requested_id for another location is refused.
    Returns the location id as text, or None when an admin asked for none and
    required=False (= all commissaries).
    """
    if _is_admin():
        if not requested_id:
            if required:
                raise CommissaryAccessError('Choose a commissary', 400)
            return None
        if not is_commissary_location(conn, requested_id):
            raise CommissaryAccessError('That location is not a commissary', 400)
        return str(requested_id)

    own = _get_user_location(conn)
    if not own:
        raise CommissaryAccessError('No location is linked to your account', 403)
    own = str(own)
    if requested_id and str(requested_id) != own:
        raise CommissaryAccessError('You do not have access to that commissary', 403)
    if not is_commissary_location(conn, own):
        raise CommissaryAccessError('Your location is not a commissary', 403)
    return own
