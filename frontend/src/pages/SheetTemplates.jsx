import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import './catalog.css'
import './sheet-templates.css'

export default function SheetTemplates() {
  const navigate = useNavigate()

  const [templates, setTemplates] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [activeFilter, setActiveFilter] = useState('active') // 'active' | 'inactive' | 'all'

  // Create modal
  const [showCreate,  setShowCreate]  = useState(false)
  const [creating,    setCreating]    = useState(false)
  const [createForm,  setCreateForm]  = useState({ name: '', notes: '' })
  const [createError, setCreateError] = useState(null)

  const fetchTemplates = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = {}
      if (activeFilter === 'inactive') params.show_inactive = 'true'
      if (activeFilter === 'all')      params.show_inactive = 'true'
      const res = await axios.get('/api/sheet-templates', { params })
      // Filter client-side for 'inactive' only
      const data = activeFilter === 'inactive'
        ? res.data.filter(t => !t.active)
        : res.data
      setTemplates(data)
    } catch (e) {
      setError('Failed to load templates.')
    } finally {
      setLoading(false)
    }
  }, [activeFilter])

  useEffect(() => { fetchTemplates() }, [fetchTemplates])

  const handleCreate = async () => {
    if (!createForm.name.trim()) return
    setCreating(true)
    setCreateError(null)
    try {
      const res = await axios.post('/api/sheet-templates', createForm)
      setShowCreate(false)
      setCreateForm({ name: '', notes: '' })
      navigate(`/sheet-templates/${res.data.id}`)
    } catch (e) {
      setCreateError(e.response?.data?.error || 'Failed to create template.')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Count Sheet Templates</h1>
          <p className="page-subtitle">{templates.length} templates</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          + New Template
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Filter bar */}
      <div className="filter-bar" style={{ marginBottom: '1rem' }}>
        <div className="btn-group">
          {['active', 'inactive', 'all'].map(f => (
            <button
              key={f}
              className={`btn btn-sm ${activeFilter === f ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActiveFilter(f)}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="spinner">Loading templates...</div>
      ) : templates.length === 0 ? (
        <div className="card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          No templates yet. Create one to get started.
        </div>
      ) : (
        <div className="template-grid">
          {templates.map(t => (
            <div key={t.id} className="template-card"
              onClick={() => navigate(`/sheet-templates/${t.id}`)}>
              <div className="template-card-header">
                <span className="template-name">{t.name}</span>
                <span className={`badge ${t.active ? 'badge-success' : 'badge-neutral'}`}>
                  {t.active ? 'Active' : 'Inactive'}
                </span>
              </div>
              <div className="template-meta">
                <span>{t.section_count || 0} sections</span>
                <span>·</span>
                <span>{t.location_count || 0} locations</span>
              </div>
              {t.notes && (
                <p className="template-notes">{t.notes}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => { setShowCreate(false); setCreateError(null) }}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">New Template</h2>
              <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>✕</button>
            </div>
            <div className="modal-body">
              {createError && <div className="alert alert-error">{createError}</div>}
              <div className="form-group">
                <label className="form-label">Name *</label>
                <input className="input" placeholder="e.g. Morning Count Sheet"
                  value={createForm.name} autoFocus
                  onChange={e => setCreateForm(f => ({ ...f, name: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && handleCreate()} />
              </div>
              <div className="form-group">
                <label className="form-label">Notes</label>
                <textarea className="input" rows={2} placeholder="Optional description"
                  value={createForm.notes}
                  onChange={e => setCreateForm(f => ({ ...f, notes: e.target.value }))} />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleCreate}
                disabled={creating || !createForm.name.trim()}>
                {creating ? 'Creating...' : 'Create Template'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
