// =============================================================================
// InventoryDailyPage.jsx  —  /inventory/daily
// =============================================================================
// The daily inventory for one store: every product the store inventories, with
// the day's count (latest submitted inventory wins) shown in one chosen unit per
// product. Products not counted that day show their last count in grey.
// Data: GET /api/inventory/daily (backend/features/inventory/inventory_daily_routes.py)
// =============================================================================
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import { useDebounce } from '../../../core/hooks/useDebounce'
import { formatDateShort, formatTimestamp, parseLocalDate } from '../../../core/utils/dateUtils.js'
import '../../../core/styles/shared-ui.css'
import './InventoryDailyPage.css'

const SOURCE_BADGE = {
  count_sheet: { cls: 'badge-info',    label: 'Count Sheet' },
  manual:      { cls: 'badge-warning', label: 'Manual' },
}

// Today in the browser's time zone, as YYYY-MM-DD (not UTC)
const localToday = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// "Wed, Nov 11" (the year only when it is not this year)
const fmtDay = (d) => {
  const dt = parseLocalDate(d)
  if (!dt) return ''
  const opts = { weekday: 'short', month: 'short', day: 'numeric' }
  if (dt.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric'
  return dt.toLocaleDateString('en-US', opts)
}

const fmtQty = (q) =>
  q == null ? '' : parseFloat(q).toLocaleString(undefined, { maximumFractionDigits: 2 })

export default function InventoryDailyPage() {
  const navigate    = useNavigate()
  const { isAdmin } = useAuth()

  const [locations,   setLocations]   = useState([])
  const [categories,  setCategories]  = useState([])
  const [vendors,     setVendors]     = useState([])

  const [locationId,  setLocationId]  = useState('')
  const [date,        setDate]        = useState(localToday())
  const [search,      setSearch]      = useState('')
  const [categoryId,  setCategoryId]  = useState('')
  const [vendorId,    setVendorId]    = useState('')
  const [countedOnly, setCountedOnly] = useState(false)
  const debouncedSearch = useDebounce(search, 300)

  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  // ── Static lists ───────────────────────────────────────────────────────────
  useEffect(() => {
    const calls = [axios.get('/api/categories'), axios.get('/api/vendors')]
    if (isAdmin) calls.push(axios.get('/api/locations'))
    Promise.all(calls)
      .then(([cat, ven, loc]) => {
        setCategories(cat.data)
        setVendors(ven.data)
        if (loc) setLocations(loc.data)
      })
      .catch(e => console.error('Failed to load filters', e))
  }, [isAdmin])

  // ── The day ────────────────────────────────────────────────────────────────
  const fetchDaily = useCallback(async () => {
    if (isAdmin && !locationId) { setData(null); return }
    if (!date) return
    setLoading(true)
    setError(null)
    try {
      const params = { date }
      if (isAdmin)         params.location_id  = locationId
      if (debouncedSearch) params.search       = debouncedSearch
      if (categoryId)      params.category_id  = categoryId
      if (vendorId)        params.vendor_id    = vendorId
      if (countedOnly)     params.counted_only = 'true'
      const res = await axios.get('/api/inventory/daily', { params })
      setData(res.data)
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to load the daily inventory.')
    } finally {
      setLoading(false)
    }
  }, [isAdmin, locationId, date, debouncedSearch, categoryId, vendorId, countedOnly])

  useEffect(() => { fetchDaily() }, [fetchDaily])

  // Group by category, keeping the server's order
  const groups = []
  ;(data?.products || []).forEach(p => {
    const name = p.category || 'Uncategorized'
    let g = groups[groups.length - 1]
    if (!g || g.name !== name) { g = { name, items: [] }; groups.push(g) }
    g.items.push(p)
  })
  const total = data?.products?.length || 0

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Daily Inventory</h1>
          <p className="page-subtitle">
            {data
              ? <>{data.location_name} · {formatDateShort(data.date)} · {data.counted} of {total} counted</>
              : 'What was on hand each day, from the latest submitted count'}
          </p>
        </div>
        <button className="btn btn-secondary" onClick={() => navigate('/inventory')}>Inventories</button>
      </div>

      {/* Filters */}
      <div className="filter-bar">
        {isAdmin && (
          <select className="input filter-select" value={locationId}
            onChange={e => setLocationId(e.target.value)}>
            <option value="">Select location...</option>
            {locations.map(l => (
              <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>
            ))}
          </select>
        )}
        <input className="input filter-select" type="date" value={date}
          onChange={e => setDate(e.target.value)} />
        <input className="input filter-search" placeholder="Search products..."
          value={search} onChange={e => setSearch(e.target.value)} />
        <select className="input filter-select" value={categoryId}
          onChange={e => setCategoryId(e.target.value)}>
          <option value="">All Categories</option>
          {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select className="input filter-select" value={vendorId}
          onChange={e => setVendorId(e.target.value)}>
          <option value="">All Vendors</option>
          {vendors.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
        </select>
        <label className="filter-toggle">
          <input type="checkbox" checked={countedOnly}
            onChange={e => setCountedOnly(e.target.checked)} />
          Counted only
        </label>
      </div>

      {isAdmin && !locationId && (
        <div className="card daily-empty">Select a location to see its daily inventory.</div>
      )}
      {error && <div className="alert alert-error">{error}</div>}
      {loading && !data && <div className="spinner">Loading...</div>}

      {data && total === 0 && !loading && (
        <div className="card daily-empty">
          {countedOnly ? 'Nothing was counted on this day.' : 'No products found.'}
        </div>
      )}

      {data && total > 0 && (
        <div className="table-wrap">
          <table className="daily-table">
            <thead>
              <tr>
                <th>Product</th>
                <th className="daily-qty-col">On Hand</th>
                <th>Counted On</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {groups.map(g => [
                <tr key={`cat-${g.name}`} className="daily-category-row">
                  <td colSpan={4}>{g.name}</td>
                </tr>,
                ...g.items.map(p => {
                  const badge = SOURCE_BADGE[p.source]
                  const showBase = p.counted && p.base_unit && p.unit !== p.base_unit
                  return (
                    <tr key={p.product_id}
                      className={`${p.inventory_id ? 'row-link' : ''} ${p.counted ? '' : 'daily-not-counted'}`}
                      onClick={() => p.inventory_id && navigate(`/inventory/${p.inventory_id}`)}>
                      <td>
                        <div className="daily-product">{p.product_name}</div>
                        {p.vendor_name && <div className="daily-sub">{p.vendor_name}</div>}
                      </td>

                      <td className="daily-qty-col">
                        {p.counted ? (
                          <>
                            <div className="daily-qty">
                              {fmtQty(p.quantity)} <span className="daily-unit">{p.unit}</span>
                            </div>
                            {showBase && (
                              <div className="daily-sub">= {fmtQty(p.base_quantity)} {p.base_unit}</div>
                            )}
                            {!p.converted && p.display_unit && p.display_unit !== p.unit && (
                              <div className="daily-warn" title="Add a conversion on the product to show it in this unit">
                                no conversion to {p.display_unit}
                              </div>
                            )}
                          </>
                        ) : p.last_count_date ? (
                          <div className="daily-last" title="Not counted on this day">
                            {fmtQty(p.last_quantity)} {p.last_unit}
                            <div className="daily-last-date">last counted {fmtDay(p.last_count_date)}</div>
                          </div>
                        ) : (
                          <div className="daily-last">never counted</div>
                        )}
                      </td>

                      <td>
                        {p.counted && badge && (
                          <>
                            <span className={`badge ${badge.cls}`}>{badge.label}</span>
                            {p.template_name && <span className="daily-sub-inline"> {p.template_name}</span>}
                          </>
                        )}
                        {p.replaced_count > 0 && (
                          <span className="daily-replaced"
                            title="Another inventory also counted this product today; the latest submitted one is shown">
                            replaced {p.replaced_count} earlier
                          </span>
                        )}
                      </td>

                      <td>
                        {p.counted && (
                          <>
                            <div className="daily-sub-inline">{p.counted_by || '—'}</div>
                            {p.submitted_at && <div className="daily-sub">{formatTimestamp(p.submitted_at)}</div>}
                          </>
                        )}
                      </td>
                    </tr>
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
