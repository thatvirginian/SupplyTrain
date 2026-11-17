// =============================================================================
// features/usage/pages/UsagePage.jsx      URL: /usage
// =============================================================================
// Actual usage for one store, count to count (each "window" = from one count to
// the next). Counts are end of day, so a window is labelled by the days it
// covers: Monday count -> Wednesday count = Tue -> Wed.
// Which counts make the windows: order sheets (OH), inventories, or all.
// Per product: the normal regular usage per window (median of the last 4 usual
// windows for that order day), totals for the range, and every window with how
// its number was reached:
//   start + received + transfers in - transfers out - end = actual
//   actual - extra orders = regular
// Each received order / transfer / count opens its source.
// Data: GET /api/usage (backend/features/usage/usage_routes.py)
// =============================================================================
import { useState, useEffect, useCallback, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import { useDebounce } from '../../../core/hooks/useDebounce.js'
import { parseLocalDate } from '../../../core/utils/dateUtils.js'
import '../../../core/styles/shared-ui.css'
import './UsagePage.css'

const localDay = (offset = 0) => {
  const d = new Date()
  d.setDate(d.getDate() + offset)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// "Mon 11/9"
const fmtDay = (s) => {
  const d = parseLocalDate(s)
  return d ? `${d.toLocaleDateString('en-US', { weekday: 'short' })} ${d.getMonth() + 1}/${d.getDate()}` : ''
}

const SHORT_DAY = { Monday: 'Mon', Tuesday: 'Tue', Wednesday: 'Wed', Thursday: 'Thu', Friday: 'Fri', Saturday: 'Sat', Sunday: 'Sun' }

// Which counts make the windows (?source=)
const SOURCES = [
  { value: 'oh',  label: 'Order sheets', title: 'Windows between order sheets (OH): usage as the ordering sees it' },
  { value: 'inv', label: 'Inventories',  title: 'Windows between standalone inventories (not order sheets)' },
  { value: 'all', label: 'All counts',   title: "Windows between every day's count, whatever it came from" },
]

const SOURCE_LINK = { order: id => `/orders/${id}`, transfer: id => `/transfers/${id}` }

const COUNTS_AS = {
  received:     '+ received',
  extra:        '− extra order',
  transfer_in:  '+ transfer in',
  transfer_out: '− transfer out',
}

export default function UsagePage() {
  const navigate    = useNavigate()
  const { isAdmin } = useAuth()

  const [locations,  setLocations]  = useState([])
  const [categories, setCategories] = useState([])
  const [locationId, setLocationId] = useState('')
  const [dateFrom,   setDateFrom]   = useState(localDay(-28))
  const [dateTo,     setDateTo]     = useState(localDay(0))
  const [search,     setSearch]     = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [inBase,     setInBase]     = useState(false)    // show base units instead of display units
  const [source,     setSource]     = useState('oh')     // oh | inv | all
  const debouncedSearch = useDebounce(search, 300)

  const [data,     setData]     = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)
  const [open,     setOpen]     = useState(new Set())    // product ids expanded
  const [openWin,  setOpenWin]  = useState(new Set())    // `${pid}:${start}` with sources shown

  useEffect(() => {
    // Categories are admin-only on the server; others just don't get the filter
    axios.get('/api/categories').then(r => setCategories(Array.isArray(r.data) ? r.data : [])).catch(() => {})
    if (isAdmin) axios.get('/api/locations').then(r => setLocations(r.data)).catch(() => {})
  }, [isAdmin])

  const fetchUsage = useCallback(async () => {
    if (isAdmin && !locationId) { setData(null); return }
    if (!dateFrom || !dateTo) return
    setLoading(true)
    setError(null)
    try {
      const params = { date_from: dateFrom, date_to: dateTo, source }
      if (isAdmin)         params.location_id = locationId
      if (debouncedSearch) params.search      = debouncedSearch
      if (categoryId)      params.category_id = categoryId
      const res = await axios.get('/api/usage', { params })
      setData(res.data)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not load usage.')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [isAdmin, locationId, dateFrom, dateTo, debouncedSearch, categoryId, source])

  useEffect(() => { fetchUsage() }, [fetchUsage])

  const toggle = (setFn, key) => setFn(prev => {
    const n = new Set(prev)
    if (n.has(key)) n.delete(key); else n.add(key)
    return n
  })

  // Amounts arrive in base units; show in the product's display unit unless "base" is on
  const qty = (p, v) => {
    if (v === null || v === undefined) return '—'
    const n = inBase ? v : v / (p.display_factor || 1)
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
  }
  const unitOf = (p) => inBase ? p.base_unit : p.display_unit

  // Group by category (server sorts by category, then name)
  const groups = []
  ;(data?.products || []).forEach(p => {
    const name = p.category || 'Uncategorized'
    let g = groups[groups.length - 1]
    if (!g || g.name !== name) { g = { name, items: [] }; groups.push(g) }
    g.items.push(p)
  })

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Usage</h1>
          <p className="page-subtitle">
            {data
              ? <>{data.location_name} · {SOURCES.find(x => x.value === data.source)?.label.toLowerCase()} · regular = actual − extra orders</>
              : 'What each store used between counts'}
          </p>
        </div>
      </div>

      <div className="filter-bar">
        {isAdmin && (
          <select className="input filter-select" value={locationId} onChange={e => setLocationId(e.target.value)}>
            <option value="">Select location...</option>
            {locations.map(l => <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>)}
          </select>
        )}
        <input className="input usage-date" type="date" value={dateFrom} aria-label="From"
          onChange={e => setDateFrom(e.target.value)} />
        <span className="usage-to">to</span>
        <input className="input usage-date" type="date" value={dateTo} aria-label="To"
          onChange={e => setDateTo(e.target.value)} />
        <input className="input filter-search" placeholder="Search products..."
          value={search} onChange={e => setSearch(e.target.value)} />
        {categories.length > 0 && (
          <select className="input filter-select" value={categoryId} onChange={e => setCategoryId(e.target.value)}>
            <option value="">All Categories</option>
            {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
        <div className="usage-source" role="group" aria-label="Counts used">
          {SOURCES.map(x => (
            <button key={x.value} type="button" title={x.title}
              className={source === x.value ? 'is-active' : ''} onClick={() => setSource(x.value)}>
              {x.label}
            </button>
          ))}
        </div>
        <label className="filter-toggle">
          <input type="checkbox" checked={inBase} onChange={e => setInBase(e.target.checked)} />
          Base units
        </label>
      </div>

      {isAdmin && !locationId && <div className="card usage-empty">Select a location to see its usage.</div>}
      {error && <div className="alert alert-error">{error}</div>}
      {loading && !data && <div className="spinner">Loading...</div>}

      {data?.pending_orders?.length > 0 && (
        <div className="alert alert-warning">
          {data.pending_orders.length} order{data.pending_orders.length === 1 ? ' was' : 's were'} shipped but not received yet,
          so usage around {data.pending_orders.length === 1 ? 'its' : 'their'} delivery is incomplete:{' '}
          {data.pending_orders.map((o, i) => (
            <Fragment key={o.id}>
              {i > 0 && ', '}
              <a className="usage-link" onClick={() => navigate(`/orders/${o.id}`)}>
                #{o.id} {o.vendor_name}{o.expected_date ? ` (${fmtDay(o.expected_date)})` : ''}
              </a>
            </Fragment>
          ))}
        </div>
      )}

      {data && data.products.length === 0 && !loading && (
        <div className="card usage-empty">
          No usage in this range. Usage needs two counts of a product from the chosen source
          ({SOURCES.find(x => x.value === source)?.label.toLowerCase()}); check the dates, the source, and that the counts were submitted.
        </div>
      )}

      {data && data.products.length > 0 && (
        <div className="table-wrap">
          <table className="usage-table">
            <thead>
              <tr>
                <th>Product</th>
                <th title="Per par day (the day of the count and order): median regular usage of the last 4 usual windows that order has to cover">Median per par day</th>
                <th className="usage-num">Actual</th>
                <th className="usage-num">Extra orders</th>
                <th className="usage-num">Regular</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {groups.map(g => [
                <tr key={`cat-${g.name}`} className="usage-category-row"><td colSpan={6}>{g.name}</td></tr>,
                ...g.items.map(p => {
                  const isOpen = open.has(p.product_id)
                  return (
                    <Fragment key={p.product_id}>
                      <tr className="row-link" onClick={() => toggle(setOpen, p.product_id)}>
                        <td>
                          <span className="usage-caret">{isOpen ? '▾' : '▸'}</span>
                          <span className="usage-product">{p.product_name}</span>
                          <div className="usage-sub">{unitOf(p)} · {p.windows.length} window{p.windows.length === 1 ? '' : 's'}</div>
                        </td>
                        <td>
                          {p.normal_by_order_day.length === 0
                            ? <span className="usage-sub">no usual windows yet</span>
                            : p.normal_by_order_day.map(n => (
                              <span key={n.order_day} className="usage-chip"
                                title={`${n.order_day} par: what the ${n.order_day} order has to cover, ${n.covers} (${n.days} day${n.days === 1 ? '' : 's'}). Median of the last ${n.windows} window${n.windows === 1 ? '' : 's'}`}>
                                {SHORT_DAY[n.order_day]} <b>{qty(p, n.median_regular)}</b>
                                <span className="usage-chip-covers">{n.covers}</span>
                                {n.windows < 4 && <span className="usage-chip-n">({n.windows})</span>}
                              </span>
                            ))}
                        </td>
                        <td className="usage-num">{qty(p, p.totals.actual)}</td>
                        <td className="usage-num usage-extra">{p.totals.extra ? qty(p, p.totals.extra) : '—'}</td>
                        <td className="usage-num usage-strong">{qty(p, p.totals.regular)}</td>
                        <td>{p.flag_count > 0 && <span className="usage-flag-count" title="Windows with something to check">⚠ {p.flag_count}</span>}</td>
                      </tr>

                      {isOpen && (
                        <tr className="usage-detail-row">
                          <td colSpan={6}>
                            <WindowTable p={p} qty={qty} openWin={openWin}
                              toggleWin={k => toggle(setOpenWin, k)} navigate={navigate} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                }),
              ])}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function WindowTable({ p, qty, openWin, toggleWin, navigate }) {
  return (
    <table className="usage-windows">
      <thead>
        <tr>
          <th title="Counts are end of day: the Monday count to the Wednesday count covers Tue → Wed">Days covered</th>
          <th className="usage-num">Start</th>
          <th className="usage-num">+ Received</th>
          <th className="usage-num">± Transfers</th>
          <th className="usage-num">− End</th>
          <th className="usage-num">= Actual</th>
          <th className="usage-num">− Extra</th>
          <th className="usage-num">= Regular</th>
        </tr>
      </thead>
      <tbody>
        {p.windows.map(w => {
          const key = `${p.product_id}:${w.start_date}`
          const shown = openWin.has(key)
          const net = w.transfers_in - w.transfers_out
          return (
            <Fragment key={key}>
              <tr className={`row-link ${w.usual ? '' : 'usage-off'}`} onClick={() => toggleWin(key)}>
                <td>
                  <span className="usage-caret">{shown ? '▾' : '▸'}</span>
                  {w.covers_from === w.end_date ? fmtDay(w.end_date) : <>{fmtDay(w.covers_from)} → {fmtDay(w.end_date)}</>}
                  {!w.usual && (
                    <span className="usage-tag" title={w.flags.find(f => f.code.endsWith('_than_usual'))?.text}>
                      {w.flags.some(f => f.code === 'longer_than_usual') ? 'missed count' : 'extra count'}
                    </span>
                  )}
                  {w.flags.filter(f => !f.code.endsWith('_than_usual')).map(f => (
                    <span key={f.code} className="usage-tag usage-tag-warn" title={f.text}>⚠</span>
                  ))}
                </td>
                <td className="usage-num">{qty(p, w.start)}</td>
                <td className="usage-num">{w.received ? qty(p, w.received) : '—'}</td>
                <td className="usage-num">{net ? (net > 0 ? '+' : '−') + qty(p, Math.abs(net)) : '—'}</td>
                <td className="usage-num">{qty(p, w.end)}</td>
                <td className="usage-num usage-strong">{qty(p, w.actual)}</td>
                <td className="usage-num usage-extra">{w.extra ? qty(p, w.extra) : '—'}</td>
                <td className={`usage-num usage-strong ${w.regular < 0 ? 'usage-neg' : ''}`}>{qty(p, w.regular)}</td>
              </tr>
              {shown && (
                <tr className="usage-sources-row">
                  <td colSpan={8}>
                    <ul className="usage-sources">
                      <li>
                        <span className="usage-src-date">{fmtDay(w.start_date)}</span>
                        <a className="usage-link" onClick={() => w.start_inventory_id && navigate(`/inventory/${w.start_inventory_id}`)}>Start count</a>
                        <span className="usage-src-as">on hand</span>
                        <span className="usage-src-qty">{qty(p, w.start)}</span>
                      </li>
                      {w.sources.map((s, i) => (
                        <li key={i}>
                          <span className="usage-src-date">{fmtDay(s.date)}</span>
                          <a className="usage-link" onClick={() => navigate(SOURCE_LINK[s.type](s.id))}>{s.label}</a>
                          <span className="usage-src-as">{COUNTS_AS[s.counts_as]}</span>
                          <span className="usage-src-qty">{qty(p, s.base_quantity)}</span>
                        </li>
                      ))}
                      <li>
                        <span className="usage-src-date">{fmtDay(w.end_date)}</span>
                        <a className="usage-link" onClick={() => w.end_inventory_id && navigate(`/inventory/${w.end_inventory_id}`)}>End count</a>
                        <span className="usage-src-as">− on hand</span>
                        <span className="usage-src-qty">{qty(p, w.end)}</span>
                      </li>
                      {w.flags.map(f => <li key={f.code} className="usage-src-flag">⚠ {f.text}</li>)}
                    </ul>
                  </td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}
