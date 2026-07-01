import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useDebounce } from '../hooks/useDebounce'
import './catalog.css'
import './vendor-items.css'

export default function VendorItems() {
  const navigate = useNavigate()

  // ── State ──────────────────────────────────────────────────────────────────
  const [items,      setItems]      = useState([])
  const [vendors,    setVendors]    = useState([])
  const [units,      setUnits]      = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)

  // Filters
  const [search,    setSearch]    = useState('')
  const [vendorId,  setVendorId]  = useState('')
  const [linked,    setLinked]    = useState('false')   // default: unlinked
  const [hasCode,   setHasCode]   = useState('')

  const debouncedSearch = useDebounce(search, 300)

  // Pagination
  const [page,  setPage]  = useState(1)
  const [total, setTotal] = useState(0)
  const PER_PAGE = 50

  // Create modal
  const [showCreate,  setShowCreate]  = useState(false)
  const [creating,    setCreating]    = useState(false)
  const [createForm,  setCreateForm]  = useState({
    vendor_id: '', name: '', vendor_code: '', packaging: '',
    order_unit_id: '', order_quantity: '', price: '',
    product_id: '', notes: ''
  })

  // Product search inside modal
  const [productSearch,   setProductSearch]   = useState('')
  const [productResults,  setProductResults]  = useState([])
  const [selectedProduct, setSelectedProduct] = useState(null)
  const debouncedProductSearch = useDebounce(productSearch, 300)

  // Edit modal
  const [editItem,    setEditItem]    = useState(null)
  const [editForm,    setEditForm]    = useState({})
  const [savingEdit,  setSavingEdit]  = useState(false)
  const [editError,   setEditError]   = useState(null)

  // Create error
  const [createError, setCreateError] = useState(null)

  // Product search inside edit modal
  const [editProductSearch,   setEditProductSearch]   = useState('')
  const [editProductResults,  setEditProductResults]  = useState([])
  const [editSelectedProduct, setEditSelectedProduct] = useState(null)
  const debouncedEditProductSearch = useDebounce(editProductSearch, 300)

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchItems = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = { page, per_page: PER_PAGE }
      if (debouncedSearch) params.search    = debouncedSearch
      if (vendorId)         params.vendor_id = vendorId
      if (linked)           params.linked    = linked
      if (hasCode)          params.has_code  = hasCode

      const res = await axios.get('/api/vendor-items', { params })
      setItems(res.data.vendor_items)
      setTotal(res.data.total)
    } catch (e) {
      setError('Failed to load vendor items.')
    } finally {
      setLoading(false)
    }
  }, [debouncedSearch, vendorId, linked, hasCode, page])

  const fetchVendors = useCallback(async () => {
    try {
      const res = await axios.get('/api/vendors')
      setVendors(res.data)
    } catch (e) {
      console.error('Failed to load vendors', e)
    }
  }, [])

  const fetchUnits = useCallback(async () => {
    try {
      const res = await axios.get('/api/units')
      setUnits(res.data)
    } catch (e) {
      console.error('Failed to load units', e)
    }
  }, [])

  useEffect(() => { fetchVendors(); fetchUnits() }, [fetchVendors, fetchUnits])
  useEffect(() => { setPage(1) }, [debouncedSearch, vendorId, linked, hasCode])
  useEffect(() => { fetchItems() }, [fetchItems])

  // Product search inside create modal
  useEffect(() => {
    if (!debouncedProductSearch || debouncedProductSearch.length < 2) {
      setProductResults([])
      return
    }
    axios.get('/api/products', { params: { search: debouncedProductSearch, per_page: 8 } })
      .then(res => setProductResults(res.data.products))
      .catch(() => setProductResults([]))
  }, [debouncedProductSearch])

  // ── Create vendor item ─────────────────────────────────────────────────────
  const handleCreate = async () => {
    if (!createForm.vendor_id || !createForm.name.trim()) return
    setCreating(true)
    setCreateError(null)
    try {
      await axios.post('/api/vendor-items', {
        ...createForm,
        product_id: selectedProduct?.id || null,
      })
      setShowCreate(false)
      setCreateForm({
        vendor_id: '', name: '', vendor_code: '', packaging: '',
        order_unit_id: '', order_quantity: '', price: '',
        product_id: '', notes: ''
      })
      setSelectedProduct(null)
      setProductSearch('')
      fetchItems()
    } catch (e) {
      setCreateError(e.response?.data?.error || 'Failed to create vendor item.')
    } finally {
      setCreating(false)
    }
  }

  // Product search inside edit modal
  useEffect(() => {
    if (!debouncedEditProductSearch || debouncedEditProductSearch.length < 2) {
      setEditProductResults([])
      return
    }
    axios.get('/api/products', { params: { search: debouncedEditProductSearch, per_page: 8 } })
      .then(res => setEditProductResults(res.data.products))
      .catch(() => setEditProductResults([]))
  }, [debouncedEditProductSearch])

  // ── Activate vendor item ───────────────────────────────────────────────────
  const handleActivate = async (itemId) => {
    try {
      await axios.post(`/api/vendor-items/${itemId}/activate`)
      fetchItems()
    } catch (e) {
      console.error('Failed to activate vendor item', e)
    }
  }

  // ── Edit vendor item ───────────────────────────────────────────────────────
  const openEdit = (item) => {
    setEditItem(item)
    setEditForm({
      vendor_code:    item.vendor_code || '',
      packaging:      item.packaging || '',
      order_unit_id:  item.order_unit_id ? String(item.order_unit_id) : '',
      order_quantity: item.order_quantity || '',
      price:          item.price || '',
      notes:          item.notes || '',
    })
    // Pre-populate linked product if it exists
    if (item.product_id) {
      setEditSelectedProduct({ id: item.product_id, name: item.product_name })
    } else {
      setEditSelectedProduct(null)
    }
    setEditProductSearch('')
    setEditProductResults([])
  }

  const handleSaveEdit = async () => {
    setSavingEdit(true)
    setEditError(null)
    try {
      await axios.put(`/api/vendor-items/${editItem.id}`, {
        ...editForm,
        product_id: editSelectedProduct?.id || null,
      })
      setEditItem(null)
      setEditSelectedProduct(null)
      fetchItems()
    } catch (e) {
      setEditError(e.response?.data?.error || 'Failed to save vendor item.')
    } finally {
      setSavingEdit(false)
    }
  }

  // ── Derived ────────────────────────────────────────────────────────────────
  const pages = Math.ceil(total / PER_PAGE)

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="page">

      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Vendor Items</h1>
          <p className="page-subtitle">{total} items</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          + New Vendor Item
        </button>
      </div>

      {/* Filters */}
      <div className="filter-bar">
        <input
          className="input filter-search"
          placeholder="Search name or code..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />

        <select className="input filter-select" value={vendorId}
          onChange={e => setVendorId(e.target.value)}>
          <option value="">All Vendors</option>
          {vendors.map(v => (
            <option key={v.id} value={v.id}>{v.name}</option>
          ))}
        </select>

        <select className="input filter-select" value={linked}
          onChange={e => setLinked(e.target.value)}>
          <option value="">All</option>
          <option value="false">Unlinked</option>
          <option value="true">Linked</option>
        </select>

        <select className="input filter-select" value={hasCode}
          onChange={e => setHasCode(e.target.value)}>
          <option value="">Any Code Status</option>
          <option value="true">Has Code</option>
          <option value="false">No Code</option>
        </select>
      </div>

      {/* Error */}
      {error && <div className="alert alert-error">{error}</div>}

      {/* Table */}
      {loading ? (
        <div className="spinner">Loading vendor items...</div>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Vendor Item</th>
                  <th>Vendor</th>
                  <th>Code</th>
                  <th>Packaging</th>
                  <th>Price</th>
                  <th>Linked Product</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
                      No vendor items found.
                    </td>
                  </tr>
                ) : items.map(item => (
                  <tr key={item.id}>
                    <td>
                      <span className="product-name">{item.vendor_item_name}</span>
                    </td>
                    <td style={{ color: 'var(--text-secondary)' }}>{item.vendor_name}</td>
                    <td>
                      {item.vendor_code
                        ? <span className="vi-code">{item.vendor_code}</span>
                        : <span style={{ color: 'var(--text-muted)' }}>—</span>
                      }
                    </td>
                    <td style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                      {item.packaging || '—'}
                    </td>
                    <td style={{ color: 'var(--text-secondary)' }}>
                      {item.price ? `$${parseFloat(item.price).toFixed(2)}` : '—'}
                    </td>
                    <td>
                      {item.product_id ? (
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => navigate(`/products/${item.product_id}`)}
                        >
                          {item.product_name}
                        </button>
                      ) : (
                        <span className="badge badge-warning">Unlinked</span>
                      )}
                    </td>
                    <td>
                      {item.active
                        ? <span className="badge badge-success">Active</span>
                        : <span className="badge badge-neutral">Inactive</span>
                      }
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.4rem' }}>
                        {item.product_id && !item.active && (
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => handleActivate(item.id)}
                          >
                            Set Active
                          </button>
                        )}
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => openEdit(item)}
                        >
                          Edit
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {pages > 1 && (
            <div className="pagination">
              <button className="btn btn-ghost" disabled={page === 1}
                onClick={() => setPage(p => p - 1)}>← Prev</button>
              <span className="pagination-info">Page {page} of {pages}</span>
              <button className="btn btn-ghost" disabled={page === pages}
                onClick={() => setPage(p => p + 1)}>Next →</button>
            </div>
          )}
        </>
      )}

      {/* ── Create Vendor Item Modal ── */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => { setShowCreate(false); setCreateError(null) }}>
          <div className="modal modal--wide" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">New Vendor Item</h2>
              <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>✕</button>
            </div>
            <div className="modal-body">

              {createError && (
                <div className="alert alert-error">{createError}</div>
              )}

              {/* Vendor */}
              <div className="form-group">
                <label className="form-label">Vendor *</label>
                <select className="input" value={createForm.vendor_id}
                  onChange={e => setCreateForm(f => ({ ...f, vendor_id: e.target.value }))}>
                  <option value="">Select vendor...</option>
                  {vendors.map(v => (
                    <option key={v.id} value={v.id}>{v.name}</option>
                  ))}
                </select>
              </div>

              {/* Name */}
              <div className="form-group">
                <label className="form-label">Vendor Item Name *</label>
                <input className="input" placeholder="e.g. Chicken Breast 40lb Case"
                  value={createForm.name}
                  onChange={e => setCreateForm(f => ({ ...f, name: e.target.value }))}
                  autoFocus />
              </div>

              {/* Code + Packaging */}
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Vendor Code</label>
                  <input className="input" placeholder="e.g. 247409"
                    value={createForm.vendor_code}
                    onChange={e => setCreateForm(f => ({ ...f, vendor_code: e.target.value }))} />
                </div>
                <div className="form-group">
                  <label className="form-label">Packaging</label>
                  <input className="input" placeholder="e.g. Case/40/4OZ"
                    value={createForm.packaging}
                    onChange={e => setCreateForm(f => ({ ...f, packaging: e.target.value }))} />
                </div>
              </div>

              {/* Unit + Quantity + Price */}
              <div className="form-row form-row--3">
                <div className="form-group">
                  <label className="form-label">Order Unit</label>
                  <select className="input" value={createForm.order_unit_id}
                    onChange={e => setCreateForm(f => ({ ...f, order_unit_id: e.target.value }))}>
                    <option value="">Select unit...</option>
                    {units.map(u => (
                      <option key={u.id} value={u.id}>{u.display} ({u.name})</option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Qty per Unit</label>
                  <input className="input" type="number" placeholder="e.g. 40"
                    value={createForm.order_quantity}
                    onChange={e => setCreateForm(f => ({ ...f, order_quantity: e.target.value }))} />
                </div>
                <div className="form-group">
                  <label className="form-label">Price</label>
                  <input className="input" type="number" step="0.01" placeholder="e.g. 44.53"
                    value={createForm.price}
                    onChange={e => setCreateForm(f => ({ ...f, price: e.target.value }))} />
                </div>
              </div>

              {/* Link to product */}
              <div className="form-group">
                <label className="form-label">Link to Product</label>
                {selectedProduct ? (
                  <div className="product-selected">
                    <span>{selectedProduct.name}</span>
                    <button className="btn btn-ghost btn-sm"
                      onClick={() => { setSelectedProduct(null); setProductSearch('') }}>
                      ✕
                    </button>
                  </div>
                ) : (
                  <>
                    <input className="input" placeholder="Search products..."
                      value={productSearch}
                      onChange={e => setProductSearch(e.target.value)} />
                    {productResults.length > 0 && (
                      <div className="product-search-results">
                        {productResults.map(p => (
                          <button key={p.id} className="product-search-result"
                            onClick={() => {
                              setSelectedProduct(p)
                              setProductSearch('')
                              setProductResults([])
                            }}>
                            <span>{p.name}</span>
                            <span className="result-meta">{p.category_name}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Notes */}
              <div className="form-group">
                <label className="form-label">Notes</label>
                <input className="input" placeholder="Optional"
                  value={createForm.notes}
                  onChange={e => setCreateForm(f => ({ ...f, notes: e.target.value }))} />
              </div>

            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleCreate}
                disabled={creating || !createForm.vendor_id || !createForm.name.trim()}>
                {creating ? 'Creating...' : 'Create Vendor Item'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Edit Vendor Item Modal ── */}
      {editItem && (
        <div className="modal-overlay" onClick={() => { setEditItem(null); setEditError(null) }}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Edit Vendor Item</h2>
              <button className="btn btn-ghost" onClick={() => setEditItem(null)}>✕</button>
            </div>
            <div className="modal-body">
              {editError && (
                <div className="alert alert-error">{editError}</div>
              )}
              <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.5rem' }}>
                {editItem.vendor_name} · {editItem.vendor_item_name}
              </p>
              <div className="form-group">
                <label className="form-label">Vendor Code</label>
                <input className="input" placeholder="e.g. 247409"
                  value={editForm.vendor_code}
                  onChange={e => setEditForm(f => ({ ...f, vendor_code: e.target.value }))} />
              </div>
              <div className="form-group">
                <label className="form-label">Packaging</label>
                <input className="input" placeholder="e.g. Case/40/4OZ"
                  value={editForm.packaging}
                  onChange={e => setEditForm(f => ({ ...f, packaging: e.target.value }))} />
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Order Unit</label>
                  <select className="input" value={editForm.order_unit_id}
                    onChange={e => setEditForm(f => ({ ...f, order_unit_id: e.target.value }))}>
                    <option value="">Select unit...</option>
                    {units.map(u => (
                      <option key={u.id} value={u.id}>{u.display} ({u.name})</option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Qty per Unit</label>
                  <input className="input" type="number"
                    value={editForm.order_quantity}
                    onChange={e => setEditForm(f => ({ ...f, order_quantity: e.target.value }))} />
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">Price</label>
                <input className="input" type="number" step="0.01"
                  value={editForm.price}
                  onChange={e => setEditForm(f => ({ ...f, price: e.target.value }))} />
              </div>
              <div className="form-group">
                <label className="form-label">Notes</label>
                <input className="input"
                  value={editForm.notes}
                  onChange={e => setEditForm(f => ({ ...f, notes: e.target.value }))} />
              </div>

              {/* Link to product */}
              <div className="form-group">
                <label className="form-label">Linked Product</label>
                {editSelectedProduct ? (
                  <div className="product-selected">
                    <span>{editSelectedProduct.name}</span>
                    <button className="btn btn-ghost btn-sm"
                      onClick={() => { setEditSelectedProduct(null); setEditProductSearch('') }}>
                      ✕
                    </button>
                  </div>
                ) : (
                  <>
                    <input className="input" placeholder="Search products to link..."
                      value={editProductSearch}
                      onChange={e => setEditProductSearch(e.target.value)} />
                    {editProductResults.length > 0 && (
                      <div className="product-search-results">
                        {editProductResults.map(p => (
                          <button key={p.id} className="product-search-result"
                            onClick={() => {
                              setEditSelectedProduct(p)
                              setEditProductSearch('')
                              setEditProductResults([])
                            }}>
                            <span>{p.name}</span>
                            <span className="result-meta">{p.category_name}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setEditItem(null)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleSaveEdit} disabled={savingEdit}>
                {savingEdit ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
