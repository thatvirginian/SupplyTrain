import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import './catalog.css'
import './sheet-templates.css'

export default function InventoryTemplates() {
  const navigate = useNavigate()

  const [templates, setTemplates] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [filter,    setFilter]    = useState('active') // active | inactive | all

  // Add template modal
  const [showAdd,  setShowAdd]  = useState(false)
  const [adding,   setAdding]   = useState(false)
  const [newName,  setNewName]  = useState('')
  const [newNotes, setNewNotes] = useState('')

  const fetchTemplates = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (filter === 'inactive') params.show_inactive = 'true'
      if (filter === 'all')      params.show_inactive = 'true'
      const res = await axios.get('/api/inventory-templates', { params })
      let data = res.data
      if (filter === 'inactive') data = data.filter(t => !t.active)
      if (filter === 'active')   data = data.filter(t => t.active)
      setTemplates(data)
    } catch (e) {
      console.error('Failed to load templates', e)
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { fetchTemplates() }, [fetchTemplates])

  const handleAdd = async () => {
    if (!newName.trim()) return
    setAdding(true)
    try {
      const res = await axios.post('/api/inventory-templates', {
        name:  newName.trim(),
        notes: newNotes.trim() || null,
      })
      setShowAdd(false)
      setNewName('')
      setNewNotes('')
      navigate(`/inventory-templates/${res.data.id}`)
    } catch (e) {
      console.error('Failed to create template', e)
    } finally {
      setAdding(false)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Inventory Templates</h1>
          <p className="page-subtitle">{templates.length} templates</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
          + New Template
        </button>
      </div>

      {/* Filter tabs */}
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

      {loading ? (
        <div className="spinner">Loading...</div>
      ) : templates.length === 0 ? (
        <div className="page-empty">
          <p>No {filter !== 'all' ? filter : ''} inventory templates.</p>
        </div>
      ) : (
        <div className="template-list">
          {templates.map(t => (
            <div key={t.id} className="template-card"
              onClick={() => navigate(`/inventory-templates/${t.id}`)}>
              <div className="template-card-header">
                <span className="template-name">{t.name}</span>
                <span className={`badge ${t.active ? 'badge-success' : 'badge-neutral'}`}>
                  {t.active ? 'Active' : 'Inactive'}
                </span>
              </div>
              <div className="template-meta">
                {t.section_count || 0} sections ·{' '}
                {t.location_count || 0} locations
                {t.notes && <span> · {t.notes}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add modal */}
      {showAdd && (
        <div className="modal-overlay" onClick={() => setShowAdd(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">New Inventory Template</h2>
              <button className="btn btn-ghost" onClick={() => setShowAdd(false)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">Name *</label>
                <input className="input" placeholder="e.g. Weekly Inventory"
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
