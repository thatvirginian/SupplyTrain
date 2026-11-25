import { useState, useEffect, useRef } from 'react'
import axios from 'axios'

// Storage areas of a commissary (storage_areas_plan.md): Main + sites.
//
//   useStorageAreas(locationId, isAdmin) -> areas ([] when the location has none, e.g. a store)
//   <AreaSelect>      pick ONE area (production run / inventory start), or "All areas" with allowAll
//   <AreaMultiSelect> pick SEVERAL areas (Production Plan Comm Inv); Main by default

export function useStorageAreas(locationId, isAdmin) {
  const [areas, setAreas] = useState([])
  useEffect(() => {
    if (isAdmin && !locationId) { setAreas([]); return }
    let alive = true
    axios.get('/api/storage-areas', { params: isAdmin ? { location_id: locationId } : {} })
      .then(res => { if (alive) setAreas(res.data || []) })
      .catch(() => { if (alive) setAreas([]) })
    return () => { alive = false }
  }, [locationId, isAdmin])
  return areas
}

export function mainArea(areas) {
  return areas.find(a => a.kind === 'main') || null
}

export function AreaSelect({ areas, value, onChange, allowAll = false, label, style }) {
  if (!areas || areas.length < 2) return null           // only Main: nothing to choose
  return (
    <select className="input" style={{ width: 'auto', ...style }} aria-label={label || 'Storage area'}
      value={value ?? ''} onChange={e => onChange(e.target.value ? parseInt(e.target.value) : null)}>
      {allowAll && <option value="">All areas</option>}
      {areas.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
    </select>
  )
}

export function AreaMultiSelect({ areas, value, onChange, label = 'Areas' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const close = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  if (!areas || areas.length < 2) return null
  const chosen = areas.filter(a => value.includes(a.id))
  const text = chosen.length ? chosen.map(a => a.name).join(' + ') : 'Main'
  const toggle = id => {
    const next = value.includes(id) ? value.filter(x => x !== id) : [...value, id]
    onChange(next.length ? next : [mainArea(areas)?.id].filter(Boolean))   // never empty
  }
  return (
    <div className="area-multi" ref={ref}>
      <button type="button" className="btn btn-secondary btn-sm area-multi-btn"
        aria-haspopup="true" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        {label}: {text} ▾
      </button>
      {open && (
        <div className="area-multi-menu" role="menu">
          {areas.map(a => (
            <label key={a.id} className="area-multi-item">
              <input type="checkbox" checked={value.includes(a.id)} onChange={() => toggle(a.id)} />
              {a.name}{a.kind === 'main' && <span className="prod-muted"> (production)</span>}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}
