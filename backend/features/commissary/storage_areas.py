# =============================================================================
# backend/features/commissary/storage_areas.py
# =============================================================================
# Storage areas: the places a commissary keeps stock (storage_areas_plan.md).
# Every commissary has a Main area (where production happens); sites are added
# by an admin. A count (inventory, a production run's End Inv) belongs to ONE
# area; NULL storage_area_id on a run / inventory means Main.
#
#   list_areas(conn, location_id, include_inactive=False) -> [area dict], Main first
#   ensure_main(conn, location_id, user)  -> Main's id (creates it when missing)
#   resolve_area(conn, location_id, area_id) -> area dict for a new run / inventory:
#        area_id None -> Main (or None when the location has no areas);
#        refuses an area of another location, or an inactive one (AreaError)
# =============================================================================

from sqlalchemy import text


class AreaError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def list_areas(conn, location_id, include_inactive=False):
    rows = conn.execute(text(f"""
        SELECT id, location_id, name, kind, restocked, notes, active, sort_order
        FROM storage_areas
        WHERE location_id = :lid {'' if include_inactive else 'AND active = TRUE'}
        ORDER BY (kind = 'main') DESC, sort_order, lower(name)
    """), {'lid': str(location_id)}).mappings().all()
    return [dict(r) for r in rows]


def ensure_main(conn, location_id, user=None):
    row = conn.execute(text("""
        SELECT id FROM storage_areas WHERE location_id = :lid AND kind = 'main'
    """), {'lid': str(location_id)}).fetchone()
    if row:
        return row.id
    return conn.execute(text("""
        INSERT INTO storage_areas (location_id, name, kind, restocked, sort_order, created_by)
        VALUES (:lid, 'Main', 'main', FALSE, 0, :by) RETURNING id
    """), {'lid': str(location_id), 'by': user}).fetchone().id


def resolve_area(conn, location_id, area_id):
    """The area a new production run / inventory is for (None: Main, or no areas at all)."""
    if area_id in (None, '', 'main'):
        row = conn.execute(text("""
            SELECT id, name, kind FROM storage_areas WHERE location_id = :lid AND kind = 'main'
        """), {'lid': str(location_id)}).mappings().fetchone()
        return dict(row) if row else None
    try:
        area_id = int(area_id)
    except (TypeError, ValueError):
        raise AreaError('Unknown storage area')
    row = conn.execute(text("""
        SELECT id, name, kind, active, location_id FROM storage_areas WHERE id = :id
    """), {'id': area_id}).mappings().fetchone()
    if not row or str(row['location_id']) != str(location_id):
        raise AreaError('That storage area does not belong to this location')
    if not row['active']:
        raise AreaError('That storage area is switched off')
    return {'id': row['id'], 'name': row['name'], 'kind': row['kind']}
