import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import '../../../core/styles/shared-ui.css'
import './ProductionPages.css'

// Storage Areas (admin): the places a commissary keeps stock. Main is where
// production happens (every commissary has one); sites are other places stock
// is kept. "Restocked" marks sites the truck restocks regularly (storage-only
// sites are not). Counts per area come from production runs' End Inv and from
// inventories started for that area. See storage_areas_plan.md.

export default function StorageAreasPage() {
  const navigate = useNavigate()
  const [commissaries, setCommissaries] = useState(null)
  const [locationId,   setLocationId]   = useState(() => {
    try { return localStorage.getItem('production-location') || '' } catch { return '' }
  })
  const [areas,   setAreas]   = useState([])
  const [error,   setError]   = useState(null)
  const [saving,  setSaving]  = useState(false)
  const [editing, setEditing] = useState(null)       // area id being edited
  const [form,    setForm]    = useState({})
  const [adding,  setAdding]  = useState(false)
  const [newArea, setNewArea] = useState({ name: '', restocked: true, notes: '' })

  useEffect(() => {
    axios.get('/api/commissary-locations')
      .then(res => {
        setCommissaries(res.data)
        setLocationId(prev => res.data.some(c => c.store_guid === prev) ? prev : (res.data[0]?.store_guid || ''))
      })
      .catch(e => { setCommissaries([]); setError(e.response?.data?.error || 'Could not load commissaries.') })
  }, [])

  const load = useCallback(async () => {
    if (!locationId) return
    try {
      const res = await axios.get('/api/storage-areas', { params: { location_id: locationId, include_inactive: 'true' } })
      setAreas(res.data)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not load the storage areas.')
    }
  }, [locationId])

  useEffect(() => { load() }, [load])

  const fail = (e, fallback) => setError(e.response?.data?.error || fallback)

  const add = async () => {
    setSaving(true); setError(null)
    try {
      await axios.post('/api/storage-areas', { location_id: locationId, ...newArea })
      setAdding(false)
      setNewArea({ name: '', restocked: true, notes: '' })
      load()
    } catch (e) { fail(e, 'Could not add the area.') }
    finally { setSaving(false) }
  }

  const save = async (id, body) => {
    setSaving(true); setError(null)
    try {
      await axios.put(`/api/storage-areas/${id}`, body)
      setEditing(null)
      load()
    } catch (e) { fail(e, 'Could not save the area.') }
    finally { setSaving(false) }
  }

  const commissary = commissaries?.find(c => c.store_guid === locationId)

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Storage Areas</h1>
          <p className="page-subtitle">{commissary?.location_name || 'Commissary'} · where its stock is kept</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {commissaries && commissaries.length > 1 && (
            <select className="input" style={{ width: 'auto' }} value={locationId}
              onChange={e => setLocationId(e.target.value)}>
              {commissaries.map(c => <option key={c.store_guid} value={c.store_guid}>{c.location_name}</option>)}
            </select>
          )}
          <button className="btn btn-secondary" onClick={() => navigate('/commissary-stock')}>Commissary Stock</button>
          <button className="btn btn-primary" onClick={() => setAdding(true)} disabled={!locationId}>+ Add Site</button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        <div className="table-wrap" style={{ border: 'none', borderRadius: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Area</th>
                <th>Kind</th>
                <th>Restocked</th>
                <th>Notes</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {areas.map(a => editing === a.id ? (
                <tr key={a.id}>
                  <td><input className="input" value={form.name} autoFocus
                    onChange={e => setForm(f => ({ ...f, name: e.target.value }))} /></td>
                  <td className="prod-muted">{a.kind === 'main' ? 'Main (production)' : 'Site'}</td>
                  <td>{a.kind === 'main' ? '—' : (
                    <input type="checkbox" checked={form.restocked} aria-label="Restocked regularly"
                      onChange={e => setForm(f => ({ ...f, restocked: e.target.checked }))} />
                  )}</td>
                  <td><input className="input" value={form.notes} placeholder="Address, what is kept there…"
                    onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} /></td>
                  <td></td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <button className="btn btn-primary btn-sm" disabled={saving || !form.name.trim()}
                      onClick={() => save(a.id, form)}>Save</button>{' '}
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button>
                  </td>
                </tr>
              ) : (
                <tr key={a.id} style={a.active ? undefined : { opacity: 0.55 }}>
                  <td style={{ fontWeight: 600 }}>{a.name}</td>
                  <td className="prod-muted">{a.kind === 'main' ? 'Main (production)' : 'Site'}</td>
                  <td>{a.kind === 'main' ? '—' : a.restocked
                    ? <span className="badge badge-info">Restocked</span>
                    : <span className="badge badge-neutral">Storage only</span>}</td>
                  <td style={{ color: 'var(--text-secondary)' }}>{a.notes || ''}</td>
                  <td>{a.active
                    ? <span className="badge badge-success">Active</span>
                    : <span className="badge badge-neutral">Off</span>}</td>
                  <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => {
                      setEditing(a.id)
                      setForm({ name: a.name, restocked: a.restocked, notes: a.notes || '' })
                    }}>Edit</button>
                    {a.kind !== 'main' && (
                      <button className="btn btn-ghost btn-sm" onClick={() => save(a.id, { active: !a.active })}>
                        {a.active ? 'Switch off' : 'Switch on'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {areas.length === 0 && (
                <tr><td colSpan={6} className="prod-muted">No areas yet. Adding a site also creates Main.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="card-body prod-muted" style={{ fontSize: '0.78rem' }}>
          Counts per area come from production runs (choose the area when you start a run; End Inv counts that
          area) and from inventories started for that area. A new site needs an opening count before its stock
          shows anywhere.
        </div>
      </div>

      {adding && (
        <div className="modal-overlay" onClick={() => setAdding(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Add a site to {commissary?.location_name || 'the commissary'}</h2>
              <button className="btn btn-ghost" onClick={() => setAdding(false)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">Name *</label>
                <input className="input" value={newArea.name} autoFocus placeholder="e.g. North Freezer"
                  onChange={e => setNewArea(a => ({ ...a, name: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && newArea.name.trim() && add()} />
              </div>
              <label style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', fontSize: '0.85rem', marginBottom: '0.75rem' }}>
                <input type="checkbox" checked={newArea.restocked}
                  onChange={e => setNewArea(a => ({ ...a, restocked: e.target.checked }))} />
                Restocked regularly by truck (off = storage only)
              </label>
              <div className="form-group">
                <label className="form-label">Notes</label>
                <input className="input" value={newArea.notes} placeholder="Address, what is kept there…"
                  onChange={e => setNewArea(a => ({ ...a, notes: e.target.value }))} />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setAdding(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={add} disabled={saving || !newArea.name.trim()}>
                {saving ? 'Adding...' : 'Add Site'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
