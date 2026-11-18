// =============================================================================
// features/usage/components/UsageFilters.jsx
// =============================================================================
// Shared by the Usage section's reports (Usage Report, Par Check):
//   useUsageReport(url)   filter state + loads the report from `url`
//   <UsageFilterBar f />  store (admins), dates, search, category, which
//                         counts make the windows, base units
//   <PendingOrders />     orders shipped but not received (usage incomplete)
//   fmtDay, SHORT_DAY, SOURCES, makeQty
// =============================================================================
import { useState, useEffect, useCallback, Fragment } from 'react'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import { useDebounce } from '../../../core/hooks/useDebounce.js'
import { parseLocalDate } from '../../../core/utils/dateUtils.js'

export const localDay = (offset = 0) => {
  const d = new Date()
  d.setDate(d.getDate() + offset)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// "Mon 11/9"
export const fmtDay = (s) => {
  const d = parseLocalDate(s)
  return d ? `${d.toLocaleDateString('en-US', { weekday: 'short' })} ${d.getMonth() + 1}/${d.getDate()}` : ''
}

// "Thu 10/29 → Fri 10/30" (counts are end of day: a window covers the days after its start count)
export const fmtCovers = (w) =>
  w.covers_from === w.end_date ? fmtDay(w.end_date) : `${fmtDay(w.covers_from)} → ${fmtDay(w.end_date)}`

export const SHORT_DAY = { Monday: 'Mon', Tuesday: 'Tue', Wednesday: 'Wed', Thursday: 'Thu', Friday: 'Fri', Saturday: 'Sat', Sunday: 'Sun' }

// Which counts make the windows (?source=)
export const SOURCES = [
  { value: 'oh',  label: 'Order sheets', title: 'Windows between order sheets (OH): usage as the ordering sees it' },
  { value: 'inv', label: 'Inventories',  title: 'Windows between standalone inventories (not order sheets)' },
  { value: 'all', label: 'All counts',   title: "Windows between every day's count, whatever it came from" },
]

// Amounts arrive in base units; show in the product's display unit unless "base" is on
export const makeQty = (inBase) => (p, v) => {
  if (v === null || v === undefined) return '—'
  const n = inBase ? v : v / (p.display_factor || 1)
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

// Group products by category (the server sorts by category, then name)
export const groupByCategory = (products) => {
  const groups = []
  ;(products || []).forEach(p => {
    const name = p.category || 'Uncategorized'
    let g = groups[groups.length - 1]
    if (!g || g.name !== name) { g = { name, items: [] }; groups.push(g) }
    g.items.push(p)
  })
  return groups
}

export function useUsageReport(url) {
  const { isAdmin } = useAuth()
  const [locations,  setLocations]  = useState([])
  const [categories, setCategories] = useState([])
  const [locationId, setLocationId] = useState('')
  const [dateFrom,   setDateFrom]   = useState(localDay(-28))
  const [dateTo,     setDateTo]     = useState(localDay(0))
  const [search,     setSearch]     = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [inBase,     setInBase]     = useState(false)
  const [source,     setSource]     = useState('oh')     // oh | inv | all
  const debouncedSearch = useDebounce(search, 300)

  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    // Categories are admin-only on the server; others just don't get the filter
    axios.get('/api/categories').then(r => setCategories(Array.isArray(r.data) ? r.data : [])).catch(() => {})
    if (isAdmin) axios.get('/api/locations').then(r => setLocations(r.data)).catch(() => {})
  }, [isAdmin])

  const load = useCallback(async () => {
    if (isAdmin && !locationId) { setData(null); return }
    if (!dateFrom || !dateTo) return
    setLoading(true)
    setError(null)
    try {
      const params = { date_from: dateFrom, date_to: dateTo, source }
      if (isAdmin)         params.location_id = locationId
      if (debouncedSearch) params.search      = debouncedSearch
      if (categoryId)      params.category_id = categoryId
      const res = await axios.get(url, { params })
      setData(res.data)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not load the report.')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [url, isAdmin, locationId, dateFrom, dateTo, debouncedSearch, categoryId, source])

  useEffect(() => { load() }, [load])

  return {
    isAdmin, locations, categories,
    locationId, setLocationId, dateFrom, setDateFrom, dateTo, setDateTo,
    search, setSearch, categoryId, setCategoryId, inBase, setInBase, source, setSource,
    data, loading, error,
    qty: makeQty(inBase),
    unitOf: (p) => inBase ? p.base_unit : p.display_unit,
  }
}

export function UsageFilterBar({ f }) {
  return (
    <div className="filter-bar">
      {f.isAdmin && (
        <select className="input filter-select" value={f.locationId} onChange={e => f.setLocationId(e.target.value)}>
          <option value="">Select location...</option>
          {f.locations.map(l => <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>)}
        </select>
      )}
      <input className="input usage-date" type="date" value={f.dateFrom} aria-label="From"
        onChange={e => f.setDateFrom(e.target.value)} />
      <span className="usage-to">to</span>
      <input className="input usage-date" type="date" value={f.dateTo} aria-label="To"
        onChange={e => f.setDateTo(e.target.value)} />
      <input className="input filter-search" placeholder="Search products..."
        value={f.search} onChange={e => f.setSearch(e.target.value)} />
      {f.categories.length > 0 && (
        <select className="input filter-select" value={f.categoryId} onChange={e => f.setCategoryId(e.target.value)}>
          <option value="">All Categories</option>
          {f.categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      )}
      <div className="usage-source" role="group" aria-label="Counts used">
        {SOURCES.map(x => (
          <button key={x.value} type="button" title={x.title}
            className={f.source === x.value ? 'is-active' : ''} onClick={() => f.setSource(x.value)}>
            {x.label}
          </button>
        ))}
      </div>
      <label className="filter-toggle">
        <input type="checkbox" checked={f.inBase} onChange={e => f.setInBase(e.target.checked)} />
        Base units
      </label>
    </div>
  )
}

// Location prompt, errors, loading, shipped-not-received orders, empty result
export function UsageStatus({ f, navigate }) {
  const { data } = f
  return (
    <>
      {f.isAdmin && !f.locationId && <div className="card usage-empty">Select a location to see its numbers.</div>}
      {f.error && <div className="alert alert-error">{f.error}</div>}
      {f.loading && !data && <div className="spinner">Loading...</div>}

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

      {data && data.products.length === 0 && !f.loading && (
        <div className="card usage-empty">
          Nothing in this range. These reports need two counts of a product from the chosen source
          ({SOURCES.find(x => x.value === f.source)?.label.toLowerCase()}); check the dates, the source, and that the counts were submitted.
        </div>
      )}
    </>
  )
}
