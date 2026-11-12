import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatDate, formatDateShort } from '../../../core/utils/dateUtils.js'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import '../../../core/styles/shared-ui.css'
import '../../../core/styles/count-entry-sheet.css'

export default function InventoryHomePage() {
  const navigate = useNavigate()
  const { isAdmin, isManager } = useAuth()

  const [templates,   setTemplates]   = useState([])
  const [locations,   setLocations]   = useState([])    // admin only
  const [locationId,  setLocationId]  = useState('')    // admin's chosen location
  const [createError, setCreateError] = useState(null)
  const [recent,      setRecent]      = useState([])
  const [loading,     setLoading]     = useState(true)
  const [creating,    setCreating]    = useState(false)

  // New inventory form
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [countDate,        setCountDate]        = useState(
    new Date().toISOString().split('T')[0]
  )
  const [showForm, setShowForm] = useState(false)

  // Staff: their own location's templates and inventories.
  // Admins: pick a location first; templates and recent list follow it.
  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      if (isAdmin && !locationId) {
        setTemplates([])
        const recentRes = await axios.get('/api/inventory-submissions', { params: { per_page: 5 } })
        setRecent(recentRes.data.submissions || [])
        return
      }
      const params = isAdmin ? { location_id: locationId } : {}
      const [tmplRes, recentRes] = await Promise.all([
        axios.get('/api/inventory-templates', { params }),
        axios.get('/api/inventory-submissions', { params: { ...params, per_page: 5 } }),
      ])
      setTemplates(tmplRes.data)
      setRecent(recentRes.data.submissions || [])
    } catch (e) {
      console.error('Failed to load', e)
    } finally {
      setLoading(false)
    }
  }, [isAdmin, locationId])

  useEffect(() => { fetchData() }, [fetchData])

  useEffect(() => {
    if (!isAdmin) return
    axios.get('/api/locations')
      .then(res => setLocations(res.data))
      .catch(e => console.error('Failed to load locations', e))
  }, [isAdmin])

  const handleLocationChange = (value) => {
    setLocationId(value)
    setSelectedTemplate('')
    setCreateError(null)
  }

  const handleCreate = async () => {
    if (!selectedTemplate || !countDate) return
    if (isAdmin && !locationId) return
    setCreating(true)
    setCreateError(null)
    try {
      const res = await axios.post('/api/inventory-submissions', {
        template_id: parseInt(selectedTemplate),
        count_date:  countDate,
        ...(isAdmin ? { location_id: locationId } : {}),
      })
      navigate(`/inventory/entry/${res.data.id}`)
    } catch (e) {
      console.error('Failed to create inventory', e)
      setCreateError(e.response?.data?.error || 'Could not start the inventory.')
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
          {isAdmin && (
            <div className="form-group" style={{ maxWidth: '320px' }}>
              <label className="form-label">Location</label>
              <select className="input" value={locationId}
                onChange={e => handleLocationChange(e.target.value)}>
                <option value="">Select location...</option>
                {locations.map(l => (
                  <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>
                ))}
              </select>
            </div>
          )}
          {createError && <div className="alert alert-error">{createError}</div>}
          {isAdmin && !locationId ? (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              Choose a location to see its inventory templates.
            </p>
          ) : templates.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              {isAdmin ? 'No inventory templates assigned to this location.' : 'No inventory templates assigned to your location.'}
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
                  {isAdmin && <th>Location</th>}
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
                    {isAdmin && <td style={{ color: 'var(--text-secondary)' }}>{s.location_name}</td>}
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
