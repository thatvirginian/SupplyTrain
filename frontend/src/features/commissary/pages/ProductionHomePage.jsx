import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import { formatDate, formatTimestamp, todayLocal, parseLocalDate } from '../../../core/utils/dateUtils.js'
import '../../../core/styles/shared-ui.css'
import './ProductionPages.css'

// Production (commissary): start a production run, and see what was made on a
// day. A day's production = the sum of its SUBMITTED runs; drafts are listed
// but not counted.

function shiftDate(dateStr, days) {
  const d = parseLocalDate(dateStr)
  d.setDate(d.getDate() + days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmtQty(v) {
  if (v == null) return '—'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 })
}

export default function ProductionHomePage() {
  const navigate = useNavigate()
  const { isAdmin } = useAuth()

  const [commissaries, setCommissaries] = useState(null)   // null = loading
  const [locationId,   setLocationId]   = useState(() => {
    try { return localStorage.getItem('production-location') || '' } catch { return '' }
  })
  const [date,      setDate]      = useState(todayLocal())
  const [templates, setTemplates] = useState([])
  const [templateId, setTemplateId] = useState('')
  const [daily,     setDaily]     = useState(null)
  const [runs,      setRuns]      = useState([])
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState(null)
  const [creating,  setCreating]  = useState(false)
  const [createError, setCreateError] = useState(null)

  // Commissaries this user can work on (staff: just their own).
  useEffect(() => {
    axios.get('/api/commissary-locations')
      .then(res => {
        setCommissaries(res.data)
        setLocationId(prev => {
          if (res.data.some(c => c.store_guid === prev)) return prev
          return res.data.length >= 1 ? res.data[0].store_guid : ''
        })
      })
      .catch(e => {
        setCommissaries([])
        setError(e.response?.data?.error || 'Could not load commissaries.')
      })
  }, [])

  useEffect(() => {
    if (!locationId) return
    try { localStorage.setItem('production-location', locationId) } catch { /* private mode */ }
  }, [locationId])

  const locParams = isAdmin ? { location_id: locationId } : {}

  const fetchDay = useCallback(async () => {
    if (!locationId) return
    setLoading(true)
    setError(null)
    try {
      const params = isAdmin ? { location_id: locationId } : {}
      const [tRes, dRes, rRes] = await Promise.all([
        axios.get('/api/production-templates', { params: { location_id: locationId } }),
        axios.get('/api/production-daily', { params: { ...params, date } }),
        axios.get('/api/production-runs', { params: { ...params, date_from: date, date_to: date, per_page: 100 } }),
      ])
      setTemplates(tRes.data)
      setTemplateId(prev => tRes.data.some(t => String(t.id) === String(prev))
        ? prev : (tRes.data.length === 1 ? String(tRes.data[0].id) : ''))
      setDaily(dRes.data.days?.[0] || null)
      setRuns(rRes.data.runs || [])
    } catch (e) {
      setError(e.response?.data?.error || 'Could not load production.')
    } finally {
      setLoading(false)
    }
  }, [locationId, date, isAdmin])

  useEffect(() => { fetchDay() }, [fetchDay])

  const handleStart = async () => {
    if (!templateId) return
    setCreating(true)
    setCreateError(null)
    try {
      const res = await axios.post('/api/production-runs', {
        template_id: parseInt(templateId), production_date: date, ...locParams,
      })
      navigate(`/production/run/${res.data.id}`)
    } catch (e) {
      setCreateError(e.response?.data?.error || 'Could not start the production run.')
    } finally {
      setCreating(false)
    }
  }

  const commissary = commissaries?.find(c => c.store_guid === locationId)
  const products   = daily?.products || []
  const drafts     = runs.filter(r => r.status === 'draft').length

  if (commissaries && commissaries.length === 0) {
    return (
      <div className="page">
        <div className="page-header"><h1 className="page-title">Production</h1></div>
        <div className="alert alert-error">
          {error || (isAdmin
            ? 'No commissary locations found. Mark a location as a commissary (locations.is_commissary).'
            : 'Your location is not a commissary.')}
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Production</h1>
          <p className="page-subtitle">{commissary?.location_name || 'Commissary'} · what was made</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {isAdmin && commissaries && commissaries.length > 1 && (
            <select className="input" style={{ width: 'auto' }} value={locationId}
              onChange={e => setLocationId(e.target.value)}>
              {commissaries.map(c => <option key={c.store_guid} value={c.store_guid}>{c.location_name}</option>)}
            </select>
          )}
          <button className="btn btn-ghost btn-sm" onClick={() => setDate(d => shiftDate(d, -1))} title="Previous day">←</button>
          <input className="input" type="date" style={{ width: 'auto' }} value={date}
            onChange={e => e.target.value && setDate(e.target.value)} />
          <button className="btn btn-ghost btn-sm" onClick={() => setDate(d => shiftDate(d, 1))} title="Next day">→</button>
          {date !== todayLocal() && (
            <button className="btn btn-secondary btn-sm" onClick={() => setDate(todayLocal())}>Today</button>
          )}
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Start a run */}
      <div className="card" style={{ marginBottom: '1.25rem' }}>
        <div className="card-header">
          <h2 className="card-title">Start Production Run</h2>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>for {formatDate(date)}</span>
        </div>
        <div className="card-body">
          {createError && <div className="alert alert-error">{createError}</div>}
          {templates.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', margin: 0 }}>
              No production templates are assigned to this commissary yet.
            </p>
          ) : (
            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <div className="form-group" style={{ margin: 0, flex: 1, minWidth: '200px' }}>
                <label className="form-label">Template</label>
                <select className="input" value={templateId} onChange={e => setTemplateId(e.target.value)}>
                  <option value="">Select template...</option>
                  {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </div>
              <button className="btn btn-primary" onClick={handleStart}
                disabled={creating || !templateId}>
                {creating ? 'Starting...' : 'Start Run'}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Day totals */}
      <div className="card" style={{ marginBottom: '1.25rem' }}>
        <div className="card-header">
          <h2 className="card-title">Made on {formatDate(date)}</h2>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            {daily?.submitted_runs || 0} submitted {daily?.submitted_runs === 1 ? 'run' : 'runs'}
          </span>
        </div>
        {drafts > 0 && (
          <div className="alert alert-warning" style={{ margin: '0.75rem 1.25rem 0' }}>
            {drafts} draft {drafts === 1 ? 'run is' : 'runs are'} not submitted yet and not counted below.
          </div>
        )}
        {loading && !daily ? (
          <div className="spinner">Loading...</div>
        ) : products.length === 0 ? (
          <div className="card-body" style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            Nothing submitted for this day.
          </div>
        ) : (
          <div className="table-wrap" style={{ border: 'none', borderRadius: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Category</th>
                  <th style={{ textAlign: 'right' }}>Made</th>
                  <th style={{ textAlign: 'right' }}>Base</th>
                  <th style={{ textAlign: 'right' }}>Runs</th>
                </tr>
              </thead>
              <tbody>
                {products.map(p => (
                  <tr key={`${p.product_id}_${p.base_unit}`}>
                    <td>
                      {p.product_name}
                      {p.corrected && (
                        <span className="badge badge-warning" style={{ marginLeft: '0.4rem' }} title="A run was corrected after it was submitted">corrected</span>
                      )}
                    </td>
                    <td style={{ color: 'var(--text-muted)' }}>{p.category || '—'}</td>
                    <td className="prod-num">
                      {p.quantity != null ? `${fmtQty(p.quantity)} ${p.unit_name}` : <span style={{ color: 'var(--text-muted)' }} title="Entered in more than one unit">mixed units</span>}
                    </td>
                    <td className="prod-num prod-muted">
                      {fmtQty(p.base_quantity)} {p.base_unit}
                    </td>
                    <td className="prod-num">{p.runs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Runs that day */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Production Runs</h2>
        </div>
        {runs.length === 0 ? (
          <div className="card-body" style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            No production runs on this day.
          </div>
        ) : (
          <div className="table-wrap" style={{ border: 'none', borderRadius: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Template</th>
                  <th style={{ textAlign: 'right' }}>Made</th>
                  <th style={{ textAlign: 'right' }}>End Inv</th>
                  <th>By</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.id} className="row-link" onClick={() => navigate(`/production/run/${r.id}`)}>
                    <td>{formatTimestamp(r.created_at)}</td>
                    <td style={{ color: 'var(--text-secondary)' }}>{r.template_name || '—'}</td>
                    <td className="prod-num">{r.item_count}</td>
                    <td className="prod-num">{r.end_count}</td>
                    <td style={{ color: 'var(--text-muted)' }}>{r.submitted_by || r.created_by}</td>
                    <td>
                      <span className={`badge ${r.status === 'submitted' ? 'badge-success' : 'badge-warning'}`}>
                        {r.status}
                      </span>
                      {r.corrected_count > 0 && (
                        <span className="badge badge-neutral" style={{ marginLeft: '0.3rem' }}>corrected</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
