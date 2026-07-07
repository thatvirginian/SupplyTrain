import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatDate, formatDateShort } from '../utils/dateUtils.js'
import axios from 'axios'
import { useAuth } from '../App.jsx'
import './catalog.css'
import './count-sheet.css'

export default function InventoryHome() {
  const navigate = useNavigate()
  const { isAdmin, isManager } = useAuth()

  const [templates,   setTemplates]   = useState([])
  const [recent,      setRecent]      = useState([])
  const [loading,     setLoading]     = useState(true)
  const [creating,    setCreating]    = useState(false)

  // New inventory form
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [countDate,        setCountDate]        = useState(
    new Date().toISOString().split('T')[0]
  )
  const [showForm, setShowForm] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [tmplRes, recentRes] = await Promise.all([
        axios.get('/api/inventory-templates'),
        axios.get('/api/inventory-submissions', { params: { per_page: 5 } }),
      ])
      setTemplates(tmplRes.data)
      setRecent(recentRes.data.submissions || [])
    } catch (e) {
      console.error('Failed to load', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const handleCreate = async () => {
    if (!selectedTemplate || !countDate) return
    setCreating(true)
    try {
      const res = await axios.post('/api/inventory-submissions', {
        template_id: parseInt(selectedTemplate),
        count_date:  countDate,
      })
      navigate(`/inventory/entry/${res.data.id}`)
    } catch (e) {
      console.error('Failed to create inventory', e)
    } finally {
      setCreating(false)
    }
  }


  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Inventory</h1>
          <p className="page-subtitle">Start a new count or view history</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className="btn btn-secondary"
            onClick={() => navigate('/inventory/history')}>
            View History
          </button>
          {isAdmin && (
            <button className="btn btn-secondary"
              onClick={() => navigate('/inventory-templates')}>
              Templates
            </button>
          )}
        </div>
      </div>

      {/* New inventory card */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="card-header">
          <h2 className="card-title">Start New Inventory</h2>
        </div>
        <div className="card-body">
          {templates.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              No inventory templates assigned to your location.
              {isAdmin && ' Create one in Templates.'}
            </p>
          ) : (
            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <div className="form-group" style={{ margin: 0, flex: 1, minWidth: '180px' }}>
                <label className="form-label">Template</label>
                <select className="input" value={selectedTemplate}
                  onChange={e => setSelectedTemplate(e.target.value)}>
                  <option value="">Select template...</option>
                  {templates.map(t => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label className="form-label">Count Date</label>
                <input className="input" type="date" value={countDate}
                  onChange={e => setCountDate(e.target.value)} />
              </div>
              <button className="btn btn-primary"
                onClick={handleCreate}
                disabled={creating || !selectedTemplate || !countDate}>
                {creating ? 'Creating...' : 'Start Inventory'}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Recent inventories */}
      {recent.length > 0 && (
        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Recent Inventories</h2>
            <button className="btn btn-ghost btn-sm"
              onClick={() => navigate('/inventory/history')}>
              View all →
            </button>
          </div>
          <div className="table-wrap" style={{ border: 'none', borderRadius: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Template</th>
                  <th>Items</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {recent.map(s => (
                  <tr key={s.id} className="row-link"
                    onClick={() => navigate(
                      s.status === 'draft'
                        ? `/inventory/entry/${s.id}`
                        : `/inventory/${s.id}`
                    )}>
                    <td>{formatDate(s.count_date)}</td>
                    <td style={{ color: 'var(--text-secondary)' }}>
                      {s.template_name || (s.source === 'count_sheet' ? 'Count Sheet' : '—')}
                    </td>
                    <td style={{ color: 'var(--text-muted)' }}>{s.item_count}</td>
                    <td>
                      <span className={`badge ${s.status === 'submitted' ? 'badge-success' : 'badge-warning'}`}>
                        {s.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
