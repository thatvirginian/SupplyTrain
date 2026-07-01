import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import './catalog.css'
import './sheet-templates.css'

export default function CommOrderTemplates() {
  const navigate = useNavigate()

  const [templates,   setTemplates]   = useState([])
  const [locations,   setLocations]   = useState([])
  const [loading,     setLoading]     = useState(true)
  const [showCreate,  setShowCreate]  = useState(false)
  const [creating,    setCreating]    = useState(false)
  const [createForm,  setCreateForm]  = useState({ location_id: '', name: '', notes: '' })
  const [createError, setCreateError] = useState(null)

  const fetchTemplates = useCallback(async () => {
    setLoading(true)
    try {
      const [tmplRes, locRes] = await Promise.all([
        axios.get('/api/comm-order-templates'),
        axios.get('/api/locations'),
      ])
      setTemplates(tmplRes.data)
      setLocations(locRes.data)
    } catch (e) {
      console.error('Failed to load', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchTemplates() }, [fetchTemplates])

  const handleCreate = async () => {
    if (!createForm.location_id || !createForm.name.trim()) return
    setCreating(true)
    setCreateError(null)
    try {
      const res = await axios.post('/api/comm-order-templates', createForm)
      setShowCreate(false)
      setCreateForm({ location_id: '', name: '', notes: '' })
      navigate(`/comm-order-templates/${res.data.id}`)
    } catch (e) {
      setCreateError(e.response?.data?.error || 'Failed to create template.')
    } finally {
      setCreating(false)
    }
  }

  // Locations that don't have a template yet
  const assignedLocations = new Set(templates.map(t => t.location_id))
  const availableLocations = locations.filter(l => !assignedLocations.has(l.store_guid))

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Commissary Order Templates</h1>
          <p className="page-subtitle">One template per location — defines pick list sections</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          + New Template
        </button>
      </div>

      {loading ? (
        <div className="spinner">Loading...</div>
      ) : templates.length === 0 ? (
        <div className="card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          No commissary order templates yet. Create one to get started.
        </div>
      ) : (
        <div className="template-grid">
          {templates.map(t => (
            <div key={t.id} className="template-card"
              onClick={() => navigate(`/comm-order-templates/${t.id}`)}>
              <div className="template-card-header">
                <span className="template-name">{t.location_name}</span>
                <span className={`badge ${t.active ? 'badge-success' : 'badge-neutral'}`}>
                  {t.active ? 'Active' : 'Inactive'}
                </span>
              </div>
              <div className="template-meta">
                <span>{t.name}</span>
                <span>·</span>
                <span>{t.section_count || 0} sections</span>
                <span>·</span>
                <span>{t.item_count || 0} products</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => { setShowCreate(false); setCreateError(null) }}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">New Commissary Order Template</h2>
              <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>✕</button>
            </div>
            <div className="modal-body">
              {createError && <div className="alert alert-error">{createError}</div>}
              <div className="form-group">
                <label className="form-label">Location *</label>
                <select className="input" value={createForm.location_id}
                  onChange={e => setCreateForm(f => ({ ...f, location_id: e.target.value }))}>
                  <option value="">Select location...</option>
                  {availableLocations.map(l => (
                    <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>
                  ))}
                </select>
                {availableLocations.length === 0 && (
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                    All locations already have a commissary template.
                  </p>
                )}
              </div>
              <div className="form-group">
                <label className="form-label">Template Name *</label>
                <input className="input" placeholder="e.g. Chantilly Commissary Orders"
                  value={createForm.name} autoFocus
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
              <button className="btn btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleCreate}
                disabled={creating || !createForm.location_id || !createForm.name.trim()}>
                {creating ? 'Creating...' : 'Create Template'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
