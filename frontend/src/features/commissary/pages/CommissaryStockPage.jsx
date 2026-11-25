import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import { useDebounce } from '../../../core/hooks/useDebounce'
import { todayLocal, parseLocalDate } from '../../../core/utils/dateUtils.js'
import '../../../core/styles/shared-ui.css'
import './ProductionPages.css'

// Commissary Stock: what each storage area of a commissary had at its latest
// count (on or before the chosen date), per product, and the total over the
// areas. Counts only for now: restocks and picks between counts come in later
// steps (storage_areas_plan.md).

function fmt(v) {
  if (v == null) return '—'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function shortDate(d) {
  if (!d) return ''
  return parseLocalDate(d).toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric' })
}

export default function CommissaryStockPage() {
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [commissaries, setCommissaries] = useState(null)
  const [locationId,   setLocationId]   = useState(() => {
    try { return localStorage.getItem('production-location') || '' } catch { return '' }
  })
  const [date,    setDate]    = useState(todayLocal())
  const [search,  setSearch]  = useState('')
  const [data,    setData]    = useState(null)
  const [error,   setError]   = useState(null)
  const [loading, setLoading] = useState(false)
  const debounced = useDebounce(search, 250)

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
    setLoading(true); setError(null)
    try {
      const res = await axios.get('/api/storage-areas/stock', {
        params: { date, search: debounced || undefined, ...(isAdmin ? { location_id: locationId } : {}) },
      })
      setData(res.data)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not load commissary stock.')
    } finally { setLoading(false) }
  }, [locationId, date, debounced, isAdmin])

  useEffect(() => { load() }, [load])

  const commissary = commissaries?.find(c => c.store_guid === locationId)
  const areas = data?.areas || []
  const products = data?.products || []

  // Group rows by category
  const groups = []
  for (const p of products) {
    const last = groups[groups.length - 1]
    if (last && last.category === p.category) last.items.push(p)
    else groups.push({ category: p.category, items: [p] })
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Commissary Stock</h1>
          <p className="page-subtitle">
            {commissary?.location_name || 'Commissary'} · each area's latest count on or before the date
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {isAdmin && commissaries && commissaries.length > 1 && (
            <select className="input" style={{ width: 'auto' }} value={locationId}
              onChange={e => setLocationId(e.target.value)}>
              {commissaries.map(c => <option key={c.store_guid} value={c.store_guid}>{c.location_name}</option>)}
            </select>
          )}
          <input className="input" style={{ width: '180px' }} placeholder="Search products..."
            value={search} onChange={e => setSearch(e.target.value)} />
          <input className="input" type="date" style={{ width: 'auto' }} value={date}
            onChange={e => e.target.value && setDate(e.target.value)} />
          {isAdmin && (
            <button className="btn btn-secondary" onClick={() => navigate('/storage-areas')}>Storage Areas</button>
          )}
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        {loading && !data ? <div className="spinner">Loading...</div>
          : products.length === 0 ? (
            <div className="card-body prod-muted">
              {areas.length === 0 ? 'This commissary has no storage areas yet.' : 'No counts on or before this date.'}
            </div>
          ) : (
            <div className="table-wrap" style={{ border: 'none', borderRadius: 0 }}>
              <table>
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Unit</th>
                    {areas.map(a => <th key={a.id} style={{ textAlign: 'right' }}>{a.name}</th>)}
                    {areas.length > 1 && <th style={{ textAlign: 'right' }}>Total</th>}
                  </tr>
                </thead>
                <tbody>
                  {groups.map(g => [
                    <tr key={`g-${g.category}`} className="plan-section-row">
                      <td colSpan={areas.length + 3}>{g.category || 'No category'}</td>
                    </tr>,
                    ...g.items.map(p => (
                      <tr key={p.product_id}>
                        <td>
                          {p.product_name}
                          {p.missing_conversion && (
                            <span className="badge badge-warning" style={{ marginLeft: '0.4rem' }}
                              title="A count is in a base unit that no longer converts; it is left out of the total">unit?</span>
                          )}
                        </td>
                        <td className="prod-muted">{p.unit_name}</td>
                        {areas.map(a => {
                          const c = p.areas[String(a.id)]
                          return (
                            <td key={a.id} className="prod-num">
                              {c ? <>
                                {fmt(c.quantity)}
                                <span className="stock-cell-date">{shortDate(c.date)}</span>
                              </> : <span className="prod-muted">—</span>}
                            </td>
                          )
                        })}
                        {areas.length > 1 && <td className="prod-num stock-total">{fmt(p.total)}</td>}
                      </tr>
                    )),
                  ])}
                </tbody>
              </table>
            </div>
          )}
        <div className="card-body prod-muted" style={{ fontSize: '0.78rem' }}>
          Each number is that area's latest count (production run End Inv or an inventory for that area) on or
          before the date, with the day it was counted. Restocks and picks between counts are not in these
          numbers yet.
        </div>
      </div>
    </div>
  )
}
