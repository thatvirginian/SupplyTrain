import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import '../../../core/styles/shared-ui.css'
import '../../../core/styles/template-editor.css'

// Production Templates (admin, commissary GM): the sheets the commissary fills
// in to record what it made.
export default function ProductionTemplateListPage() {
  const navigate = useNavigate()

  const [templates, setTemplates] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [filter,    setFilter]    = useState('active') // active | inactive | all

  const [showAdd,  setShowAdd]  = useState(false)
  const [adding,   setAdding]   = useState(false)
  const [addError, setAddError] = useState(null)
  const [newName,  setNewName]  = useState('')
  const [newNotes, setNewNotes] = useState('')

  const fetchTemplates = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.get('/api/production-templates', {
        params: filter === 'active' ? {} : { show_inactive: 'true' },
      })
      let data = res.data
      if (filter === 'inactive') data = data.filter(t => !t.active)
      setTemplates(data)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not load production templates.')
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { fetchTemplates() }, [fetchTemplates])

  const handleAdd = async () => {
    if (!newName.trim()) return
    setAdding(true)
    setAddError(null)
    try {
      const res = await axios.post('/api/production-templates', {
        name:  newName.trim(),
        notes: newNotes.trim() || null,
      })
      navigate(`/production-templates/${res.data.id}`)
    } catch (e) {
      setAddError(e.response?.data?.error || 'Could not create the template.')
    } finally {
      setAdding(false)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Production Templates</h1>
          <p className="page-subtitle">{templates.length} templates</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
          + New Template
        </button>
      </div>

      <div className="filter-bar">
        {['active', 'inactive', 'all'].map(f => (
          <button key={f}
            className={`btn ${filter === f ? 'btn-primary' : 'btn-ghost'} btn-sm`}
            onClick={() => setFilter(f)}
            style={{ textTransform: 'capitalize' }}>
            {f}
          </button>
        ))}
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div className="spinner">Loading...</div>
      ) : templates.length === 0 ? (
        <div className="page-empty">
          <p>No {filter !== 'all' ? filter : ''} production templates.</p>
        </div>
      ) : (
        <div className="template-grid">
          {templates.map(t => (
            <div key={t.id} className="template-card"
              onClick={() => navigate(`/production-templates/${t.id}`)}>
              <div className="template-card-header">
                <span className="template-name">{t.name}</span>
                <span className={`badge ${t.active ? 'badge-success' : 'badge-neutral'}`}>
                  {t.active ? 'Active' : 'Inactive'}
                </span>
              </div>
              <div className="template-meta">
                {t.section_count || 0} sections · {t.item_count || 0} products ·{' '}
                {t.location_count || 0} {t.location_count === 1 ? 'commissary' : 'commissaries'}
                {t.notes && <span> · {t.notes}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {showAdd && (
        <div className="modal-overlay" onClick={() => setShowAdd(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">New Production Template</h2>
              <button className="btn btn-ghost" onClick={() => setShowAdd(false)}>✕</button>
            </div>
            <div className="modal-body">
              {addError && <div className="alert alert-error">{addError}</div>}
              <div className="form-group">
                <label className="form-label">Name *</label>
                <input className="input" placeholder="e.g. Daily Sauces"
                  value={newName} autoFocus
                  onChange={e => setNewName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAdd()} />
              </div>
              <div className="form-group">
                <label className="form-label">Notes</label>
                <textarea className="input" rows={2}
                  placeholder="Optional notes"
                  value={newNotes}
                  onChange={e => setNewNotes(e.target.value)} />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowAdd(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleAdd}
                disabled={adding || !newName.trim()}>
                {adding ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
