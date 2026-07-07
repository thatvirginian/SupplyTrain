import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatDate, formatDateShort } from '../utils/dateUtils.js'
import axios from 'axios'
import { useAuth } from '../App.jsx'
import './catalog.css'
import './inventory-sheet.css'

export default function CountSheetHome() {
  const navigate    = useNavigate()
  const { isAdmin } = useAuth()

  const [templates,   setTemplates]   = useState([])
  const [submissions, setSubmissions] = useState([])
  const [locations,   setLocations]   = useState([])
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)
  const [opening,     setOpening]     = useState(null)

  const today = new Date().toISOString().split('T')[0]
  const [countDate,   setCountDate]   = useState(today)
  const [locationId,  setLocationId]  = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const requests = [
        axios.get('/api/sheet-submissions', { params: { per_page: 10, location_id: locationId || undefined } }),
      ]
      if (isAdmin) requests.push(axios.get('/api/locations'))

      const results = await Promise.all(requests)
      setSubmissions(results[0].data.submissions || [])
      if (isAdmin && results[1]) {
        setLocations(results[1].data)
      }
    } catch (e) {
      setError('Failed to load sheets.')
    } finally {
      setLoading(false)
    }
  }, [isAdmin, locationId])

  const fetchTemplates = useCallback(async () => {
    // Admin must select a location first
    if (isAdmin && !locationId) {
      setTemplates([])
      return
    }
    try {
      const params = {}
      if (locationId) params.location_id = locationId
      const res = await axios.get('/api/sheet-templates', { params })
      setTemplates(res.data)
    } catch (e) {
      console.error('Failed to load templates', e)
    }
  }, [locationId, isAdmin])

  useEffect(() => { fetchData() }, [fetchData])
  useEffect(() => { fetchTemplates() }, [fetchTemplates])

  const handleOpen = async (templateId) => {
    if (isAdmin && !locationId) {
      alert('Please select a location first.')
      return
    }
    setOpening(templateId)
    try {
      const res = await axios.post('/api/sheet-submissions', {
        template_id: templateId,
        count_date:  countDate,
        location_id: isAdmin ? locationId : undefined,
      })
      navigate(`/count-sheet/${res.data.id}`)
    } catch (e) {
      console.error('Failed to open sheet', e)
    } finally {
      setOpening(null)
    }
  }

  const handleDeleteDraft = async (e, submissionId) => {
    e.stopPropagation()
    if (!confirm('Delete this draft? This cannot be undone.')) return
    try {
      await axios.delete(`/api/sheet-submissions/${submissionId}`)
      fetchData()
    } catch (e) {
      console.error('Failed to delete draft', e)
    }
  }


  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Count Sheets</h1>
          <p className="page-subtitle">Select a sheet to begin counting</p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Date + location pickers */}
      <div className="inv-filters">
        <div className="inv-date-picker">
          <label className="form-label">Count Date</label>
          <input
            className="input"
            type="date"
            value={countDate}
            onChange={e => setCountDate(e.target.value)}
          />
        </div>

        {isAdmin && (
          <div className="inv-date-picker">
            <label className="form-label">Location *</label>
            <select
              className="input"
              value={locationId}
              onChange={e => setLocationId(e.target.value)}
            >
              <option value="">Select location...</option>
              {locations.map(l => (
                <option key={l.store_guid} value={l.store_guid}>
                  {l.location_name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Templates */}
      {isAdmin && !locationId ? (
        <div className="card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          Select a location to see available count sheets.
        </div>
      ) : templates.length === 0 ? (
        <div className="card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          No count sheets available for this location.
        </div>
      ) : (
        <div className="inv-template-list">
          {templates.map(t => (
            <div key={t.id} className="inv-template-card">
              <div className="inv-template-info">
                <span className="inv-template-name">{t.name}</span>
                <span className="inv-template-meta">
                  {t.section_count || 0} sections
                </span>
              </div>
              <button
                className="btn btn-primary"
                onClick={() => handleOpen(t.id)}
                disabled={opening === t.id}>
                {opening === t.id ? 'Opening...' : 'Start Count'}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Recent submissions */}
      {submissions.length > 0 && (
        <>
          <h2 className="inv-section-title">Recent Sheets</h2>
          <div className="inv-submission-list">
            {submissions.map(s => (
              <div key={s.id} className="inv-submission-card"
                onClick={() => navigate(`/count-sheet/${s.id}`)}>
                <div className="inv-submission-info">
                  <span className="inv-template-name">{s.template_name}</span>
                  <span className="inv-template-name"> </span>
                  <span className="inv-template-meta">
                    {formatDate(s.count_date)} · {s.location_name}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span className={`badge ${s.status === 'submitted' ? 'badge-success' : 'badge-warning'}`}>
                    {s.status === 'submitted' ? 'Submitted' : 'Draft'}
                  </span>
                  {(s.status === 'draft' || isAdmin) && (
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ color: 'var(--error)' }}
                      onClick={e => handleDeleteDraft(e, s.id)}
                    >
                      Delete
                    </button>
                  )}
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>→</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
