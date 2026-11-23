import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import { formatDate, todayLocal, parseLocalDate } from '../../../core/utils/dateUtils.js'
import '../../../core/styles/shared-ui.css'
import './ProductionPages.css'

// Production Plan (commissary): the paper "Daily Prep Production" sheet.
// For one production template and one delivery date: each store's count (INV)
// and order (ORD) from the order sheets behind its commissary order, the
// totals, and what the commissary made and has left that day (from the day's
// submitted production runs and End Inv). Read only; prints on one page.

function shiftDate(dateStr, days) {
  const d = parseLocalDate(dateStr)
  d.setDate(d.getDate() + days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmt(v) {
  if (v == null) return ''
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 1 })
}

// INV top-left, ORD bottom-right, split by a diagonal like the paper sheet
function SplitCell({ inv, ord, total }) {
  const empty = inv == null && ord == null
  return (
    <td className={`plan-split ${total ? 'plan-split-total' : ''} ${empty ? 'plan-split-empty' : ''}`}>
      {!empty && <>
        <span className="plan-inv">{fmt(inv) || '–'}</span>
        <span className="plan-ord">{fmt(ord) || '–'}</span>
      </>}
    </td>
  )
}

export default function ProductionPlanPage() {
  const navigate = useNavigate()
  const { isAdmin } = useAuth()

  const [commissaries, setCommissaries] = useState(null)
  const [locationId, setLocationId] = useState(() => {
    try { return localStorage.getItem('production-location') || '' } catch { return '' }
  })
  const [templates,  setTemplates]  = useState([])
  const [templateId, setTemplateId] = useState(() => {
    try { return localStorage.getItem('production-plan-template') || '' } catch { return '' }
  })
  const [date,    setDate]    = useState(todayLocal())
  const [plan,    setPlan]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    axios.get('/api/commissary-locations')
      .then(res => {
        setCommissaries(res.data)
        setLocationId(prev => res.data.some(c => c.store_guid === prev)
          ? prev : (res.data[0]?.store_guid || ''))
      })
      .catch(e => {
        setCommissaries([])
        setError(e.response?.data?.error || 'Could not load commissaries.')
      })
  }, [])

  // Templates assigned to the commissary
  useEffect(() => {
    if (!locationId) return
    try { localStorage.setItem('production-location', locationId) } catch { /* private mode */ }
    axios.get('/api/production-templates', { params: { location_id: locationId } })
      .then(res => {
        const active = res.data.filter(t => t.active !== false)
        setTemplates(active)
        setTemplateId(prev => active.some(t => String(t.id) === String(prev))
          ? String(prev) : (active[0] ? String(active[0].id) : ''))
      })
      .catch(e => setError(e.response?.data?.error || 'Could not load production templates.'))
  }, [locationId])

  useEffect(() => {
    if (!templateId) return
    try { localStorage.setItem('production-plan-template', templateId) } catch { /* private mode */ }
  }, [templateId])

  const fetchPlan = useCallback(async () => {
    if (!locationId || !templateId) { setPlan(null); return }
    setLoading(true)
    setError(null)
    try {
      const res = await axios.get('/api/production-plan', {
        params: { template_id: templateId, date, ...(isAdmin ? { location_id: locationId } : {}) },
      })
      setPlan(res.data)
    } catch (e) {
      setPlan(null)
      setError(e.response?.data?.error || 'Could not load the production plan.')
    } finally {
      setLoading(false)
    }
  }, [locationId, templateId, date, isAdmin])

  useEffect(() => { fetchPlan() }, [fetchPlan])

  const commissary = commissaries?.find(c => c.store_guid === locationId)
  const stores     = plan?.stores || []

  // Route groups over the store columns (only when routes are set)
  const routeGroups = []
  for (const s of stores) {
    const r = s.route || ''
    const last = routeGroups[routeGroups.length - 1]
    if (last && last.route === r) last.span += 1
    else routeGroups.push({ route: r, span: 1 })
  }
  const showRoutes = routeGroups.some(g => g.route)

  if (commissaries && commissaries.length === 0) {
    return (
      <div className="page">
        <div className="page-header"><h1 className="page-title">Production Plan</h1></div>
        <div className="alert alert-error">
          {error || (isAdmin ? 'No commissary locations found.' : 'Your location is not a commissary.')}
        </div>
      </div>
    )
  }

  return (
    <div className="page plan-page">
      <div className="page-header no-print">
        <div>
          <h1 className="page-title">Production Plan</h1>
          <p className="page-subtitle">
            {commissary?.location_name || 'Commissary'} · store counts and orders for a delivery day
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {isAdmin && commissaries && commissaries.length > 1 && (
            <select className="input" style={{ width: 'auto' }} value={locationId}
              onChange={e => setLocationId(e.target.value)}>
              {commissaries.map(c => <option key={c.store_guid} value={c.store_guid}>{c.location_name}</option>)}
            </select>
          )}
          <select className="input" style={{ width: 'auto' }} value={templateId}
            onChange={e => setTemplateId(e.target.value)}>
            {templates.length === 0 && <option value="">No production templates</option>}
            {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <button className="btn btn-ghost btn-sm" onClick={() => setDate(d => shiftDate(d, -1))} title="Previous day">←</button>
          <input className="input" type="date" style={{ width: 'auto' }} value={date}
            onChange={e => e.target.value && setDate(e.target.value)} />
          <button className="btn btn-ghost btn-sm" onClick={() => setDate(d => shiftDate(d, 1))} title="Next day">→</button>
          {date !== todayLocal() && (
            <button className="btn btn-secondary btn-sm" onClick={() => setDate(todayLocal())}>Today</button>
          )}
          <button className="btn btn-secondary btn-sm" onClick={() => window.print()} disabled={!plan}>Print</button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {plan && (
        <div className="card plan-card">
          <div className="card-header plan-head">
            <div>
              <h2 className="card-title">{plan.template_name}</h2>
              <span className="plan-head-sub">
                Delivery {formatDate(plan.date)}{commissary ? ` · ${commissary.location_name}` : ''}
              </span>
            </div>
            <span className="plan-key">
              <span className="plan-key-cell"><span className="plan-inv">INV</span><span className="plan-ord">ORD</span></span>
              store count / order
            </span>
          </div>

          {plan.draft_runs > 0 && (
            <div className="alert alert-warning no-print" style={{ margin: '0.75rem 1.25rem 0' }}>
              {plan.draft_runs} draft production {plan.draft_runs === 1 ? 'run is' : 'runs are'} not
              submitted yet, so Made and End Inv leave {plan.draft_runs === 1 ? 'it' : 'them'} out.
            </div>
          )}

          {stores.length === 0 && (
            <div className="card-body" style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              No store has a commissary order for delivery on {formatDate(plan.date)}.
            </div>
          )}

          <div className="table-wrap plan-wrap">
            <table className="plan-table">
              <thead>
                {showRoutes && (
                  <tr className="plan-route-row">
                    <th colSpan={2}></th>
                    {routeGroups.map((g, i) => (
                      <th key={i} colSpan={g.span} className="plan-route">{g.route || 'No route'}</th>
                    ))}
                    <th colSpan={3}></th>
                  </tr>
                )}
                <tr>
                  <th>Product</th>
                  <th>Unit</th>
                  {stores.map(s => (
                    <th key={s.location_id} className="plan-store" title={s.location_name}>
                      <button type="button" className="plan-store-link"
                        onClick={() => s.order_ids.length === 1
                          ? navigate(`/orders/${s.order_ids[0]}`)
                          : navigate('/orders/history')}>
                        {s.abbreviation || s.location_name}
                      </button>
                    </th>
                  ))}
                  <th className="plan-store">Total</th>
                  <th className="prod-num">Made</th>
                  <th className="prod-num">End Inv</th>
                </tr>
              </thead>
              <tbody>
                {plan.sections.map(sec => (
                  <SectionRows key={sec.id} sec={sec} stores={stores}
                    showName={plan.sections.length > 1} />
                ))}
              </tbody>
            </table>
          </div>
          <div className="plan-foot">
            INV is what the store counted on its order sheet and ORD what it ordered, both shown in the
            template's unit. Made and End Inv come from this day's submitted production runs.
          </div>
        </div>
      )}
      {loading && !plan && <div className="spinner">Loading...</div>}
    </div>
  )
}

function SectionRows({ sec, stores, showName }) {
  return <>
    {showName && (
      <tr className="plan-section-row">
        <td colSpan={stores.length + 5}>{sec.name}</td>
      </tr>
    )}
    {sec.items.map(i => (
      <tr key={i.product_id}>
        <td className="plan-product">
          {i.product_name}
          {i.missing_conversion && (
            <span className="badge badge-warning" style={{ marginLeft: '0.4rem' }}
              title="A store's count or order is in a unit with no conversion to this unit; it is left out">
              unit?
            </span>
          )}
        </td>
        <td className="prod-muted">{i.unit_name}</td>
        {stores.map(s => {
          const c = i.stores[s.location_id]
          return <SplitCell key={s.location_id} inv={c?.inv} ord={c?.ord} />
        })}
        <SplitCell inv={i.total_inv} ord={i.total_ord} total />
        <td className="prod-num">{fmt(i.made)}</td>
        <td className="prod-num">{fmt(i.end_inv)}</td>
      </tr>
    ))}
  </>
}
