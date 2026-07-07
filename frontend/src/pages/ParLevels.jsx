import { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { useDebounce } from '../hooks/useDebounce'
import { NumericInput } from '../components/NumericInput.jsx'
import './catalog.css'
import './par-levels.css'

const DAYS = [
  { value: null, label: 'Default' },
  { value: 0,    label: 'Sun' },
  { value: 1,    label: 'Mon' },
  { value: 2,    label: 'Tue' },
  { value: 3,    label: 'Wed' },
  { value: 4,    label: 'Thu' },
  { value: 5,    label: 'Fri' },
  { value: 6,    label: 'Sat' },
]

export default function ParLevels() {
  // ── State ──────────────────────────────────────────────────────────────────
  const [locations,   setLocations]   = useState([])
  const [units,       setUnits]       = useState([])
  const [products,    setProducts]    = useState([])
  const [parLevels,   setParLevels]   = useState([])  // flat list from API
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState(null)
  const [total,       setTotal]       = useState(0)
  const [page,        setPage]        = useState(1)
  const PER_PAGE = 50

  const [locationId,  setLocationId]  = useState('')
  const [search,      setSearch]      = useState('')
  const [categoryId,  setCategoryId]  = useState('')
  const [vendorId,    setVendorId]    = useState('')
  const [categories,  setCategories]  = useState([])
  const [vendors,     setVendors]     = useState([])

  const debouncedSearch = useDebounce(search, 300)

  // Edit state: { `${product_id}_${day}`: { qty, unit_id } }
  const [edits,    setEdits]    = useState({})
  const [saving,   setSaving]   = useState(null)  // key being saved

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchStatic = useCallback(async () => {
    try {
      const [locRes, unitRes, catRes, vendRes] = await Promise.all([
        axios.get('/api/locations'),
        axios.get('/api/units'),
        axios.get('/api/categories'),
        axios.get('/api/vendors'),
      ])
      setLocations(locRes.data)
      setUnits(unitRes.data)
      setCategories(catRes.data)
      setVendors(vendRes.data)
    } catch (e) {
      console.error('Failed to load static data', e)
    }
  }, [])

  const fetchProducts = useCallback(async () => {
    if (!locationId) return
    setLoading(true)
    setError(null)
    try {
      const params = { page, per_page: PER_PAGE }
      if (debouncedSearch) params.search      = debouncedSearch
      if (categoryId)      params.category_id = categoryId
      const res = await axios.get('/api/products', { params })
      setProducts(res.data.products || [])
      setTotal(res.data.total || 0)
    } catch (e) {
      setError('Failed to load products.')
    } finally {
      setLoading(false)
    }
  }, [locationId, debouncedSearch, categoryId, page])

  const fetchParLevels = useCallback(async () => {
    if (!locationId) return
    try {
      const params = { location_id: locationId }
      if (vendorId) params.vendor_id = vendorId
      const res = await axios.get('/api/par-levels', { params })
      setParLevels(res.data)
    } catch (e) {
      console.error('Failed to load par levels', e)
    }
  }, [locationId, vendorId])

  // When vendor filter active, only show products that have par levels from that vendor
  const filteredProducts = vendorId
    ? products.filter(p => parLevels.some(pl => pl.product_id === p.id))
    : products
  useEffect(() => { fetchStatic() }, [fetchStatic])
  useEffect(() => { setPage(1) }, [locationId, debouncedSearch, categoryId, vendorId])
  useEffect(() => { fetchProducts() }, [fetchProducts])
  useEffect(() => { fetchParLevels() }, [fetchParLevels])

  // ── Par level helpers ──────────────────────────────────────────────────────
  // Build a map: { product_id: { day_of_week: parRow } }
  const parMap = {}
  parLevels.forEach(p => {
    if (!parMap[p.product_id]) parMap[p.product_id] = {}
    const key = p.day_of_week ?? 'default'
    parMap[p.product_id][key] = p
  })

  const getEffectivePar = (productId, day) => {
    const productPars = parMap[productId] || {}
    return productPars[day] || productPars['default'] || null
  }

  const getEditKey = (productId, day) => `${productId}_${day ?? 'default'}`

  const getEditValue = (productId, day) => {
    const key = getEditKey(productId, day)
    return edits[key] || null
  }

  const handleEditChange = (productId, day, field, value) => {
    const key = getEditKey(productId, day)
    setEdits(e => ({
      ...e,
      [key]: { ...(e[key] || {}), [field]: value }
    }))
  }

  // ── Save par level ─────────────────────────────────────────────────────────
  const handleSave = async (productId, day) => {
    const key  = getEditKey(productId, day)
    const edit = edits[key]
    if (!edit || (!edit.qty && edit.qty !== 0)) return

    // Fall back to existing par unit if none selected in edit
    const existingPar = getEffectivePar(productId, day === 'default' ? null : day)
    const unitId = edit.unit_id || existingPar?.unit_id || existingPar?.override_unit_id || existingPar?.recommended_unit_id || null

    setSaving(key)
    try {
      await axios.post('/api/par-levels', {
        product_id:       productId,
        location_id:      locationId,
        day_of_week:      day,  // null for Default, 0-6 for specific days
        override_qty:     parseFloat(edit.qty),
        override_unit_id: unitId ? parseInt(unitId) : null,
      })
      // Clear edit
      setEdits(e => {
        const next = { ...e }
        delete next[key]
        return next
      })
      fetchParLevels()
    } catch (e) {
      console.error('Failed to save par level', e)
    } finally {
      setSaving(null)
    }
  }

  // ── Clear override ─────────────────────────────────────────────────────────
  const handleClearOverride = async (parId) => {
    try {
      await axios.post(`/api/par-levels/${parId}/clear-override`)
      fetchParLevels()
    } catch (e) {
      console.error('Failed to clear override', e)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Par Levels</h1>
          <p className="page-subtitle">Set par levels per product per day</p>
        </div>
      </div>

      {/* Filters */}
      <div className="filter-bar">
        <select className="input filter-select" value={locationId}
          onChange={e => setLocationId(e.target.value)}>
          <option value="">Select location...</option>
          {locations.map(l => (
            <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>
          ))}
        </select>

        <input className="input filter-search" placeholder="Search products..."
          value={search} onChange={e => setSearch(e.target.value)} />

        <select className="input filter-select" value={categoryId}
          onChange={e => setCategoryId(e.target.value)}>
          <option value="">All Categories</option>
          {categories.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        <select className="input filter-select" value={vendorId}
          onChange={e => setVendorId(e.target.value)}>
          <option value="">All Vendors</option>
          {vendors.map(v => (
            <option key={v.id} value={v.id}>{v.name}</option>
          ))}
        </select>
      </div>

      {!locationId && (
        <div className="card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          Select a location to manage par levels.
        </div>
      )}

      {error && <div className="alert alert-error">{error}</div>}

      {locationId && !loading && filteredProducts.length === 0 && (
        <div className="card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          No products found.
        </div>
      )}

      {locationId && filteredProducts.length > 0 && (
        <>
          <div className="par-table-wrap">
          <table className="par-table">
            <thead>
              <tr>
                <th className="par-product-col">Product</th>
                {DAYS.map(d => (
                  <th key={d.label} className="par-day-col">{d.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredProducts.map(product => (
                <tr key={product.id}>
                  <td className="par-product-cell">
                    <span className="par-product-name">{product.name}</span>
                    <span className="par-product-unit">{product.base_unit}</span>
                  </td>
                  {DAYS.map(d => {
                    const par     = getEffectivePar(product.id, d.value)
                    const edit    = getEditValue(product.id, d.value)
                    const editKey = getEditKey(product.id, d.value)
                    const hasOverride = par?.override_qty != null
                    const hasRec      = par?.recommended_qty != null

                    return (
                      <td key={d.label} className="par-day-cell">
                        {edit ? (
                          // Edit mode
                          <div className="par-edit">
                            <NumericInput
                              className="par-qty-input"
                              placeholder="qty"
                              value={edit.qty ?? ''}
                              autoFocus
                              onChange={e => handleEditChange(product.id, d.value, 'qty', e.target.value)}
                              onKeyDown={e => {
                                if (e.key === 'Enter')  handleSave(product.id, d.value)
                                if (e.key === 'Escape') {
                                  setEdits(ev => {
                                    const next = { ...ev }
                                    delete next[editKey]
                                    return next
                                  })
                                }
                              }}
                            />
                            <select
                              className="par-unit-select"
                              value={edit.unit_id ?? par?.unit_id ?? ''}
                              onChange={e => handleEditChange(product.id, d.value, 'unit_id', e.target.value)}
                            >
                              <option value="">unit...</option>
                              {units.map(u => (
                                <option key={u.id} value={u.id}>{u.name}</option>
                              ))}
                            </select>
                            <div className="par-edit-actions">
                              <button className="par-save-btn"
                                disabled={saving === editKey}
                                onClick={() => handleSave(product.id, d.value)}>
                                {saving === editKey ? '...' : '✓'}
                              </button>
                              <button className="par-cancel-btn"
                                onClick={() => setEdits(ev => {
                                  const next = { ...ev }
                                  delete next[editKey]
                                  return next
                                })}>
                                ✕
                              </button>
                            </div>
                          </div>
                        ) : par ? (
                          // Display mode
                          <div className="par-display"
                            onClick={() => handleEditChange(product.id, d.value, 'qty',
                              hasOverride ? par.override_qty : par.recommended_qty)}>
                            <span className={`par-qty ${hasOverride ? 'par-overridden' : 'par-recommended'}`}>
                              {(hasOverride ? par.override_qty : par.recommended_qty) ?? '—'}
                            </span>
                            <span className="par-unit-label">
                              {par.unit_name}
                            </span>
                            {hasOverride && hasRec && (
                              <span className="par-rec-hint" title="Recommended">
                                rec: {par.recommended_qty}
                              </span>
                            )}
                            {hasOverride && (
                              <button className="par-clear-btn"
                                onClick={e => { e.stopPropagation(); handleClearOverride(par.id) }}
                                title="Clear override">
                                ↺
                              </button>
                            )}
                          </div>
                        ) : (
                          // Empty — click to add
                          <div className="par-empty"
                            onClick={() => handleEditChange(product.id, d.value, 'qty', '')}>
                            <span className="par-add-hint">+ set</span>
                          </div>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {total > PER_PAGE && (
          <div className="pagination">
            <button className="btn btn-ghost" disabled={page === 1}
              onClick={() => setPage(p => p - 1)}>← Prev</button>
            <span className="pagination-info">
              Page {page} of {Math.ceil(total / PER_PAGE)} · {total} products
            </span>
            <button className="btn btn-ghost" disabled={page >= Math.ceil(total / PER_PAGE)}
              onClick={() => setPage(p => p + 1)}>Next →</button>
          </div>
        )}
        </>
      )}
    </div>
  )
}
