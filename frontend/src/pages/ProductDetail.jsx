import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import './catalog.css'
import './product-detail.css'

export default function ProductDetail() {
  const { id }   = useParams()
  const navigate = useNavigate()

  // ── State ──────────────────────────────────────────────────────────────────
  const [product,    setProduct]    = useState(null)
  const [categories, setCategories] = useState([])
  const [units,      setUnits]      = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [saving,     setSaving]     = useState(false)
  const [saved,      setSaved]      = useState(false)

  // Edit mode
  const [editing,  setEditing]  = useState(false)
  const [editForm, setEditForm] = useState({})

  // Unit conversion modal
  const [showUnitModal, setShowUnitModal] = useState(false)
  const [unitForm,      setUnitForm]      = useState({
    from_unit_id: '', to_unit_id: '', conversion: '', notes: ''
  })
  const [savingUnit, setSavingUnit] = useState(false)

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchProduct = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.get(`/api/products/${id}`)
      setProduct(res.data)
      setEditForm({
        name:                      res.data.name,
        internal_name:             res.data.internal_name || '',
        sku:                       res.data.sku || '',
        category_id:               res.data.category_id || '',
        base_unit_id:              res.data.base_unit_id || '',
        product_type:              res.data.product_type || '',
        active:                    res.data.active,
        notes:                     res.data.notes || '',
        order_rounding_threshold:  res.data.order_rounding_threshold ?? 0.5,
      })
    } catch (e) {
      setError('Product not found.')
    } finally {
      setLoading(false)
    }
  }, [id])

  const fetchCategories = useCallback(async () => {
    try {
      const res = await axios.get('/api/categories')
      setCategories(res.data)
    } catch (e) {
      console.error('Failed to load categories', e)
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

  useEffect(() => {
    fetchProduct()
    fetchCategories()
    fetchUnits()
  }, [fetchProduct, fetchCategories, fetchUnits])

  // ── Save product edits ─────────────────────────────────────────────────────
  const handleSave = async () => {
    setSaving(true)
    try {
      await axios.put(`/api/products/${id}`, editForm)
      setEditing(false)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
      fetchProduct()
    } catch (e) {
      console.error('Failed to save product', e)
    } finally {
      setSaving(false)
    }
  }

  // ── Add unit conversion ────────────────────────────────────────────────────
  const handleAddUnit = async () => {
    setSavingUnit(true)
    try {
      await axios.post(`/api/products/${id}/units`, {
        from_unit_id: parseInt(unitForm.from_unit_id),
        conversion:   unitForm.conversion,
        notes:        unitForm.notes,
      })
      setShowUnitModal(false)
      setUnitForm({ from_unit_id: '', to_unit_id: '', conversion: '', notes: '' })
      fetchProduct()
    } catch (e) {
      console.error('Failed to add unit conversion', e)
    } finally {
      setSavingUnit(false)
    }
  }

  // ── Activate vendor item ──────────────────────────────────────────────────
  const handleActivateVendorItem = async (itemId) => {
    try {
      await axios.post(`/api/vendor-items/${itemId}/activate`)
      fetchProduct()
    } catch (e) {
      console.error('Failed to activate vendor item', e)
    }
  }

  // ── Vendor item edit modal ─────────────────────────────────────────────────
  const [editVendorItem,   setEditVendorItem]   = useState(null)
  const [vendorEditForm,   setVendorEditForm]   = useState({})
  const [savingVendorEdit, setSavingVendorEdit] = useState(false)
  const [vendorEditError,  setVendorEditError]  = useState(null)

  const openVendorEdit = (v) => {
    setEditVendorItem(v)
    setVendorEditForm({
      vendor_code:    v.vendor_code    || '',
      packaging:      v.packaging      || '',
      order_unit_id:  v.order_unit_id  ? String(v.order_unit_id) : '',
      order_quantity: v.order_quantity || '',
      price:          v.price          || '',
      notes:          v.notes          || '',
    })
    setVendorEditError(null)
  }

  const handleSaveVendorEdit = async () => {
    setSavingVendorEdit(true)
    setVendorEditError(null)
    try {
      await axios.put(`/api/vendor-items/${editVendorItem.id}`, {
        ...vendorEditForm,
        product_id: id,  // use the product ID from the URL
      })
      setEditVendorItem(null)
      fetchProduct()
    } catch (e) {
      setVendorEditError(e.response?.data?.error || 'Failed to save vendor item.')
    } finally {
      setSavingVendorEdit(false)
    }
  }

  // ── Location assignments ──────────────────────────────────────────────────
  const [assigningLocation, setAssigningLocation] = useState(null) // location_id being edited
  const [assignVendorItemId, setAssignVendorItemId] = useState('')

  const handleSetLocationVendorItem = async (locationId, assignmentId) => {
    if (!assignVendorItemId) return
    try {
      if (assignmentId) {
        // Update existing
        await axios.post('/api/location-vendor-items', {
          location_id:    locationId,
          product_id:     id,
          vendor_item_id: parseInt(assignVendorItemId),
        })
      } else {
        // Create new
        await axios.post('/api/location-vendor-items', {
          location_id:    locationId,
          product_id:     id,
          vendor_item_id: parseInt(assignVendorItemId),
        })
      }
      setAssigningLocation(null)
      setAssignVendorItemId('')
      fetchProduct()
    } catch (e) {
      console.error('Failed to set location vendor item', e)
    }
  }

  const handleRemoveLocationAssignment = async (assignmentId) => {
    try {
      await axios.delete(`/api/location-vendor-items/${assignmentId}`)
      fetchProduct()
    } catch (e) {
      console.error('Failed to remove location assignment', e)
    }
  }

  // ── Delete unit conversion ─────────────────────────────────────────────────
  const handleDeleteUnit = async (convId) => {
    if (!confirm('Delete this unit conversion?')) return
    try {
      await axios.delete(`/api/unit-conversions/${convId}`)
      fetchProduct()
    } catch (e) {
      console.error('Failed to delete unit conversion', e)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  if (loading) return <div className="spinner">Loading product...</div>
  if (error)   return <div className="page"><div className="alert alert-error">{error}</div></div>
  if (!product) return null

  const activeVendorItems  = product.vendor_items?.filter(v => v.active)  || []
  const retiredVendorItems = product.vendor_items?.filter(v => !v.active) || []
  const productUnits       = product.unit_conversions?.filter(u => u.scope === 'product') || []

  return (
    <div className="page">

      {/* ── Header ── */}
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button className="btn btn-ghost" onClick={() => navigate('/products')}>
            ← Back
          </button>
          <div>
            <h1 className="page-title">{product.name}</h1>
            <p className="page-subtitle">
              {product.category_name || 'No category'} · {product.base_unit}
            </p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {saved && <span className="save-confirm">Saved ✓</span>}
          <span className={`badge ${product.active ? 'badge-success' : 'badge-error'}`}>
            {product.active ? 'Active' : 'Inactive'}
          </span>
          {editing ? (
            <>
              <button className="btn btn-secondary" onClick={() => setEditing(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving...' : 'Save Changes'}
              </button>
            </>
          ) : (
            <button className="btn btn-secondary" onClick={() => setEditing(true)}>Edit</button>
          )}
        </div>
      </div>

      {/* ── Two column layout ── */}
      <div className="detail-grid">

        {/* ── Left column ── */}
        <div className="detail-main">

          {/* Product info */}
          <div className="card">
            <div className="card-header">
              <h2 className="card-title">Product Info</h2>
            </div>
            {editing ? (
              <div className="card-body">
                <div className="form-group">
                  <label className="form-label">Name *</label>
                  <input className="input" value={editForm.name}
                    onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} />
                </div>
                <div className="form-group">
                  <label className="form-label">Internal Name</label>
                  <input className="input" value={editForm.internal_name}
                    onChange={e => setEditForm(f => ({ ...f, internal_name: e.target.value }))} />
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Category</label>
                    <select className="input" value={editForm.category_id}
                      onChange={e => setEditForm(f => ({ ...f, category_id: e.target.value }))}>
                      <option value="">No category</option>
                      {categories.map(c => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Base Unit *</label>
                    <select className="input" value={editForm.base_unit_id}
                      onChange={e => setEditForm(f => ({ ...f, base_unit_id: e.target.value }))}>
                      <option value="">Select unit...</option>
                      {units.map(u => (
                        <option key={u.id} value={u.id}>{u.display} ({u.name})</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Product Type</label>
                    <input className="input" value={editForm.product_type}
                      placeholder="e.g. commissary"
                      onChange={e => setEditForm(f => ({ ...f, product_type: e.target.value }))} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">SKU</label>
                    <input className="input" value={editForm.sku}
                      onChange={e => setEditForm(f => ({ ...f, sku: e.target.value }))} />
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Notes</label>
                  <textarea className="input" rows={3} value={editForm.notes}
                    onChange={e => setEditForm(f => ({ ...f, notes: e.target.value }))} />
                </div>
                <div className="form-group">
                  <label className="form-label">Order Rounding Threshold</label>
                  <input className="input" type="number" min="0.01" max="1" step="0.05"
                    value={editForm.order_rounding_threshold}
                    onChange={e => setEditForm(f => ({ ...f, order_rounding_threshold: e.target.value }))} />
                  <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                    Round up when fraction ≥ this value.
                    0.1 = always round up · 0.5 = standard · 1.0 = always round down
                  </p>
                </div>
                <div className="form-group">
                  <label className="filter-toggle">
                    <input type="checkbox" checked={editForm.active}
                      onChange={e => setEditForm(f => ({ ...f, active: e.target.checked }))} />
                    Active
                  </label>
                </div>
              </div>
            ) : (
              <div className="card-body">
                <div className="info-grid">
                  <div className="info-row">
                    <span className="info-label">Name</span>
                    <span className="info-value">{product.name}</span>
                  </div>
                  {product.internal_name && product.internal_name !== product.name && (
                    <div className="info-row">
                      <span className="info-label">Internal Name</span>
                      <span className="info-value">{product.internal_name}</span>
                    </div>
                  )}
                  <div className="info-row">
                    <span className="info-label">Category</span>
                    <span className="info-value">{product.category_name || '—'}</span>
                  </div>
                  <div className="info-row">
                    <span className="info-label">Base Unit</span>
                    <span className="info-value mono">{product.base_unit}</span>
                  </div>
                  {product.product_type && (
                    <div className="info-row">
                      <span className="info-label">Type</span>
                      <span className="info-value">{product.product_type}</span>
                    </div>
                  )}
                  {product.sku && (
                    <div className="info-row">
                      <span className="info-label">SKU</span>
                      <span className="info-value mono">{product.sku}</span>
                    </div>
                  )}
                  <div className="info-row">
                    <span className="info-label">Product ID</span>
                    <span className="info-value mono">{product.id}</span>
                  </div>
                  {product.order_rounding_threshold != null && (
                    <div className="info-row">
                      <span className="info-label">Round Threshold</span>
                      <span className="info-value mono">{product.order_rounding_threshold}</span>
                    </div>
                  )}
                  {product.notes && (
                    <div className="info-row">
                      <span className="info-label">Notes</span>
                      <span className="info-value">{product.notes}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Used in recipes */}
          {product.used_in_recipes?.length > 0 && (
            <div className="card">
              <div className="card-header">
                <h2 className="card-title">Used In Recipes</h2>
              </div>
              <div className="unit-list">
                {product.used_in_recipes.map(r => (
                  <div key={r.id} className="unit-item">
                    <span className="info-value">{r.recipe_name}</span>
                    <span className="vendor-meta">
                      {r.quantity} {r.unit}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>

        {/* ── Right column ── */}
        <div className="detail-side">

          {/* Vendor items */}
          <div className="card">
            <div className="card-header">
              <h2 className="card-title">Vendor Items</h2>
              <span className="badge badge-neutral">
                {activeVendorItems.length} active
              </span>
            </div>

            {activeVendorItems.length === 0 && retiredVendorItems.length === 0 ? (
              <div className="card-body">
                <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                  No vendor items linked.
                </p>
              </div>
            ) : (
              <div className="vendor-list">
                {activeVendorItems.map(v => (
                  <div key={v.id} className="vendor-item vendor-item--active"
                    style={{ cursor: 'pointer' }}
                    onClick={() => openVendorEdit(v)}>
                    <div className="vendor-header">
                      <span className="vendor-name">{v.vendor_name}</span>
                      <span className="badge badge-success">Active</span>
                    </div>
                    <div className="vendor-item-name">{v.vendor_item_name}</div>
                    {v.vendor_code && <div className="vendor-code">{v.vendor_code}</div>}
                    {v.packaging   && <div className="vendor-meta">{v.packaging}</div>}
                    <div className="vendor-meta">
                      {v.order_quantity && `${v.order_quantity} `}
                      {v.order_unit}
                      {v.price && ` · $${parseFloat(v.price).toFixed(2)}`}
                    </div>
                  </div>
                ))}

                {retiredVendorItems.length > 0 && (
                  <>
                    <div className="vendor-divider">Inactive</div>
                    {retiredVendorItems.map(v => (
                      <div key={v.id} className="vendor-item vendor-item--retired"
                        style={{ cursor: 'pointer' }}
                        onClick={() => openVendorEdit(v)}>
                        <div className="vendor-header">
                          <span className="vendor-name">{v.vendor_name}</span>
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={e => { e.stopPropagation(); handleActivateVendorItem(v.id) }}
                          >
                            Set Active
                          </button>
                        </div>
                        <div className="vendor-item-name">{v.vendor_item_name}</div>
                        {v.vendor_code && <div className="vendor-code">{v.vendor_code}</div>}
                        {v.packaging   && <div className="vendor-meta">{v.packaging}</div>}
                        <div className="vendor-meta">
                          {v.order_quantity && `${v.order_quantity} `}
                          {v.order_unit}
                          {v.price && ` · $${parseFloat(v.price).toFixed(2)}`}
                        </div>
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>

          {/* Unit conversions — product-specific only */}
          <div className="card">
            <div className="card-header">
              <h2 className="card-title">Unit Conversions</h2>
              <button className="btn btn-secondary btn-sm"
                onClick={() => setShowUnitModal(true)}>
                + Add
              </button>
            </div>

            {productUnits.length === 0 ? (
              <div className="card-body">
                <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                  No product-specific conversions.
                  Base unit is <span className="mono">{product.base_unit}</span>.
                </p>
              </div>
            ) : (
              <div className="unit-list">
                {productUnits.map(u => (
                  <div key={u.id} className="unit-item">
                    <span className="unit-formula">
                      1 <span className="mono">{u.from_unit}</span>
                      {' = '}
                      {u.conversion} <span className="mono">{u.to_unit}</span>
                    </span>
                    <button className="btn btn-ghost btn-sm"
                      onClick={() => handleDeleteUnit(u.id)}>
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Location assignments */}
          <div className="card">
            <div className="card-header">
              <h2 className="card-title">Location Assignments</h2>
            </div>
            <div className="location-assignment-list">
              {(product.location_assignments || []).map(loc => (
                <div key={loc.location_id} className="location-assignment-row">
                  <div className="location-assignment-info">
                    <span className="section-item-name">{loc.location_name}</span>
                    {assigningLocation === loc.location_id ? (
                      <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.35rem', alignItems: 'center' }}>
                        <select className="input"
                          style={{ fontSize: '0.75rem', padding: '0.25rem 0.4rem' }}
                          value={assignVendorItemId} autoFocus
                          onChange={e => setAssignVendorItemId(e.target.value)}>
                          <option value="">Select vendor item...</option>
                          {product.vendor_items?.map(v => (
                            <option key={v.id} value={v.id}>
                              {v.vendor_name} — {v.vendor_code || 'no code'}
                            </option>
                          ))}
                        </select>
                        <button className="btn btn-primary btn-sm"
                          onClick={() => handleSetLocationVendorItem(loc.location_id, loc.assignment_id)}
                          disabled={!assignVendorItemId}>
                          Save
                        </button>
                        <button className="btn btn-ghost btn-sm"
                          onClick={() => { setAssigningLocation(null); setAssignVendorItemId('') }}>
                          ✕
                        </button>
                      </div>
                    ) : loc.assignment_id ? (
                      <div className="location-assignment-vendor">
                        <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                          {loc.vendor_name}
                          {loc.vendor_code && ` (${loc.vendor_code})`}
                        </span>
                        <span className={`badge ${loc.vendor_item_active ? 'badge-success' : 'badge-error'}`}
                          style={{ fontSize: '0.65rem' }}>
                          {loc.vendor_item_active ? 'Active' : 'Inactive'}
                        </span>
                      </div>
                    ) : (
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                        not assigned
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: '0.3rem' }}>
                    {assigningLocation !== loc.location_id && (
                      <button className="btn btn-ghost btn-sm"
                        onClick={() => {
                          setAssigningLocation(loc.location_id)
                          setAssignVendorItemId(loc.vendor_item_id ? String(loc.vendor_item_id) : '')
                        }}>
                        {loc.assignment_id ? 'Change' : 'Assign'}
                      </button>
                    )}
                    {loc.assignment_id && assigningLocation !== loc.location_id && (
                      <button className="btn btn-ghost btn-sm"
                        style={{ color: 'var(--error)' }}
                        onClick={() => handleRemoveLocationAssignment(loc.assignment_id)}>
                        ✕
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

        </div>
      </div>

      {/* ── Add Unit Conversion Modal ── */}
      {showUnitModal && (
        <div className="modal-overlay" onClick={() => setShowUnitModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Add Unit</h2>
              <button className="btn btn-ghost" onClick={() => setShowUnitModal(false)}>✕</button>
            </div>
            <div className="modal-body">
              <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '1rem' }}>
                Define how many <span className="mono">{product.base_unit}</span> are in one of your custom units.
              </p>

              <div className="form-group">
                <label className="form-label">Unit *</label>
                <select
                  className="input"
                  value={unitForm.from_unit_id}
                  onChange={e => setUnitForm(f => ({ ...f, from_unit_id: e.target.value }))}
                  autoFocus
                >
                  <option value="">Select a unit...</option>
                  {units
                    .filter(u => u.id !== product.base_unit_id)
                    .map(u => (
                      <option key={u.id} value={u.id}>{u.display} ({u.name})</option>
                    ))
                  }
                </select>
                <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                  This is what you'll select when counting or ordering this product.
                </p>
              </div>

              <div className="form-group">
                <label className="form-label">
                  How many <span className="mono">{product.base_unit}</span> in 1 of this unit? *
                </label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                    1 unit =
                  </span>
                  <input
                    className="input"
                    type="number"
                    step="any"
                    placeholder={`e.g. 5  (1 unit = 5 ${product.base_unit})`}
                    value={unitForm.conversion}
                    onChange={e => setUnitForm(f => ({ ...f, conversion: e.target.value }))}
                  />
                  <span className="mono" style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                    {product.base_unit}
                  </span>
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Notes</label>
                <input
                  className="input"
                  placeholder="Optional — e.g. 5lb retail bag"
                  value={unitForm.notes}
                  onChange={e => setUnitForm(f => ({ ...f, notes: e.target.value }))}
                />
              </div>

              {/* Preview */}
              {unitForm.from_unit_id && unitForm.conversion && (
                <div style={{
                  background: 'var(--bg-raised)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '0.6rem 0.75rem',
                  fontSize: '0.8rem',
                  color: 'var(--text-secondary)',
                }}>
                  {'1 '}
                  <span className="mono">
                    {units.find(u => String(u.id) === String(unitForm.from_unit_id))?.name || '?'}
                  </span>
                  {' = '}
                  <strong style={{ color: 'var(--text-primary)' }}>{unitForm.conversion}</strong>
                  {' '}
                  <span className="mono">{product.base_unit}</span>
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowUnitModal(false)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={handleAddUnit}
                disabled={savingUnit || !unitForm.from_unit_id || !unitForm.conversion}
              >
                {savingUnit ? 'Saving...' : 'Add Unit'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Edit Vendor Item Modal ── */}
      {editVendorItem && (
        <div className="modal-overlay" onClick={() => { setEditVendorItem(null); setVendorEditError(null) }}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Edit Vendor Item</h2>
              <button className="btn btn-ghost" onClick={() => setEditVendorItem(null)}>✕</button>
            </div>
            <div className="modal-body">
              {vendorEditError && <div className="alert alert-error">{vendorEditError}</div>}
              <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.5rem' }}>
                {editVendorItem.vendor_name} · {editVendorItem.vendor_item_name}
              </p>
              <div className="form-group">
                <label className="form-label">Vendor Code</label>
                <input className="input" placeholder="e.g. 247409"
                  value={vendorEditForm.vendor_code}
                  onChange={e => setVendorEditForm(f => ({ ...f, vendor_code: e.target.value }))} />
              </div>
              <div className="form-group">
                <label className="form-label">Packaging</label>
                <input className="input" placeholder="e.g. Case/40/4OZ"
                  value={vendorEditForm.packaging}
                  onChange={e => setVendorEditForm(f => ({ ...f, packaging: e.target.value }))} />
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Order Unit</label>
                  <select className="input" value={vendorEditForm.order_unit_id}
                    onChange={e => setVendorEditForm(f => ({ ...f, order_unit_id: e.target.value }))}>
                    <option value="">Select unit...</option>
                    {units.map(u => (
                      <option key={u.id} value={String(u.id)}>{u.display} ({u.name})</option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Qty per Unit</label>
                  <input className="input" type="number"
                    value={vendorEditForm.order_quantity}
                    onChange={e => setVendorEditForm(f => ({ ...f, order_quantity: e.target.value }))} />
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">Price</label>
                <input className="input" type="number" step="0.01"
                  value={vendorEditForm.price}
                  onChange={e => setVendorEditForm(f => ({ ...f, price: e.target.value }))} />
              </div>
              <div className="form-group">
                <label className="form-label">Notes</label>
                <input className="input"
                  value={vendorEditForm.notes}
                  onChange={e => setVendorEditForm(f => ({ ...f, notes: e.target.value }))} />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setEditVendorItem(null)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleSaveVendorEdit}
                disabled={savingVendorEdit}>
                {savingVendorEdit ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
