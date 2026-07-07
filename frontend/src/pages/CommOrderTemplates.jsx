import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import './catalog.css'
import './sheet-templates.css'

export default function CommOrderTemplates() {
  const navigate = useNavigate()

  const [templates,    setTemplates]    = useState([])
  const [locations,    setLocations]    = useState([])
  const [vendors,      setVendors]      = useState([])
  const [loading,      setLoading]      = useState(true)
  const [selectedLocs, setSelectedLocs] = useState([])

  // Create modal
  const [showCreate,   setShowCreate]   = useState(false)
  const [creating,     setCreating]     = useState(false)
  const [createForm,   setCreateForm]   = useState({
    name: '', location_id: '', vendor_id: '', notes: ''
  })
  const [createError,  setCreateError]  = useState(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (selectedLocs.length > 0) {
        params.location_id = selectedLocs
      }
      const [tmplRes, locRes, vendRes] = await Promise.all([
        axios.get('/api/comm-order-templates', { params }),
        axios.get('/api/locations'),
        axios.get('/api/vendors', { params: { is_commissary: true } }),
      ])
      setTemplates(tmplRes.data)
      setLocations(locRes.data)
      setVendors(vendRes.data.vendors || vendRes.data)
    } catch (e) {
      console.error('Failed to load', e)
    } finally {
      setLoading(false)
    }
  }, [selectedLocs])

  useEffect(() => { fetchData() }, [fetchData])

  const handleCreate = async () => {
    setCreateError(null)
    if (!createForm.location_id) { setCreateError('Select a location'); return }
    if (!createForm.vendor_id)   { setCreateError('Select a vendor');   return }
    if (!createForm.name.trim()) { setCreateError('Name is required');   return }
    setCreating(true)
    try {
      const res = await axios.post('/api/comm-order-templates', {
        location_id: createForm.location_id,
        vendor_id:   parseInt(createForm.vendor_id),
        name:        createForm.name.trim(),
        notes:       createForm.notes.trim() || null,
      })
      setShowCreate(false)
      setCreateForm({ name: '', location_id: '', vendor_id: '', notes: '' })
      navigate(`/comm-order-templates/${res.data.id}`)
    } catch (e) {
      setCreateError(e.response?.data?.error || 'Failed to create template')
    } finally {
      setCreating(false)
    }
  }

  const toggleLocation = (locId) => {
    setSelectedLocs(prev =>
      prev.includes(locId) ? prev.filter(l => l !== locId) : [...prev, locId]
    )
  }

  // Group templates by location then vendor
  const grouped = {}
  templates.forEach(t => {
    const locKey = t.location_id
    if (!grouped[locKey]) grouped[locKey] = { location_name: t.location_name, vendors: {} }
    const vendKey = t.vendor_id || 'none'
    if (!grouped[locKey].vendors[vendKey]) {
      grouped[locKey].vendors[vendKey] = { vendor_name: t.vendor_name, templates: [] }
    }
    grouped[locKey].vendors[vendKey].templates.push(t)
  })

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Commissary Templates</h1>
          <p className="page-subtitle">{templates.length} templates</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          + New Template
        </button>
      </div>

      {/* Location filter — multi select */}
      <div className="filter-bar" style={{ flexWrap: 'wrap', gap: '0.4rem' }}>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', alignSelf: 'center' }}>
          Locations:
        </span>
        <button
          className={`btn btn-sm ${selectedLocs.length === 0 ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => setSelectedLocs([])}>
          All
        </button>
        {locations.map(l => (
          <button key={l.store_guid}
            className={`btn btn-sm ${selectedLocs.includes(l.store_guid) ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => toggleLocation(l.store_guid)}>
            {l.location_name}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="spinner">Loading...</div>
      ) : templates.length === 0 ? (
        <div className="page-empty">
          <p>No commissary templates found.</p>
        </div>
      ) : (
        Object.entries(grouped).map(([locId, locData]) => (
          <div key={locId} style={{ marginBottom: '1.5rem' }}>
            {/* Location header */}
            <div style={{
              fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)',
              textTransform: 'uppercase', letterSpacing: '0.1em',
              padding: '0.5rem 0', borderBottom: '1px solid var(--border)',
              marginBottom: '0.75rem'
            }}>
              {locData.location_name}
            </div>

            {Object.entries(locData.vendors).map(([vendId, vendData]) => (
              <div key={vendId} style={{ marginBottom: '1rem' }}>
                {/* Vendor subheader */}
                <div style={{
                  fontSize: '0.75rem', fontWeight: 600,
                  color: 'var(--text-secondary)',
                  marginBottom: '0.5rem', paddingLeft: '0.25rem'
                }}>
                  {vendData.vendor_name || 'No vendor'}
                </div>

                <div className="template-grid">
                  {vendData.templates.map(t => (
                    <div key={t.id} className="template-card"
                      onClick={() => navigate(`/comm-order-templates/${t.id}`)}>
                      <div className="template-card-header">
                        <span className="template-name">{t.name}</span>
                        <span className={`badge ${t.active ? 'badge-success' : 'badge-neutral'}`}>
                          {t.active ? 'Active' : 'Inactive'}
                        </span>
                      </div>
                      <div className="template-meta">
                        <span>{t.section_count || 0} sections</span>
                        <span>·</span>
                        <span>{t.item_count || 0} items</span>
                      </div>
                      {t.notes && <p className="template-notes">{t.notes}</p>}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ))
      )}

      {/* Create modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => { setShowCreate(false); setCreateError(null) }}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">New Commissary Template</h2>
              <button className="btn btn-ghost" onClick={() => { setShowCreate(false); setCreateError(null) }}>✕</button>
            </div>
            <div className="modal-body">
              {createError && (
                <div className="alert alert-error" style={{ marginBottom: '1rem' }}>{createError}</div>
              )}
              <div className="form-group">
                <label className="form-label">Location *</label>
                <select className="input" value={createForm.location_id}
                  onChange={e => setCreateForm(f => ({ ...f, location_id: e.target.value }))}>
                  <option value="">Select location...</option>
                  {locations.map(l => (
                    <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Commissary Vendor *</label>
                <select className="input" value={createForm.vendor_id}
                  onChange={e => setCreateForm(f => ({ ...f, vendor_id: e.target.value }))}>
                  <option value="">Select vendor...</option>
                  {vendors.map(v => (
                    <option key={v.id} value={v.id}>{v.name}</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Template Name *</label>
                <input className="input" placeholder="e.g. Chantilly - Commissary 1"
                  value={createForm.name}
                  onChange={e => setCreateForm(f => ({ ...f, name: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && handleCreate()} />
              </div>
              <div className="form-group">
                <label className="form-label">Notes</label>
                <textarea className="input" rows={2}
                  value={createForm.notes}
                  onChange={e => setCreateForm(f => ({ ...f, notes: e.target.value }))} />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary"
                onClick={() => { setShowCreate(false); setCreateError(null) }}>Cancel</button>
              <button className="btn btn-primary" onClick={handleCreate} disabled={creating}>
                {creating ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
