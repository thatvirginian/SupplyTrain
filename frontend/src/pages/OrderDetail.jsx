import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../App.jsx'
import { NumericInput } from '../components/NumericInput.jsx'
import { formatDate, toDateInputValue } from '../utils/dateUtils.js'
import { useDebounce } from '../hooks/useDebounce.js'
import './catalog.css'
import './order-history.css'
import './order-detail.css'

const STATUS_BADGE = {
  draft:     'badge-warning',
  submitted: 'badge-info',
  received:  'badge-success',
  fulfilled: 'badge-success',
  cancelled: 'badge-error',
}

const POLL_INTERVAL = 30000 // 30 seconds

export default function OrderDetail() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const { isAdmin, isManager, isComm, isCommGM, isCommUser } = useAuth()

  const [order,   setOrder]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [saving,  setSaving]  = useState(false)
  const [saved,   setSaved]   = useState(false)

  // Per-item saving state — tracks which items are currently saving
  const [savingItems,       setSavingItems]       = useState(new Set())
  const [itemSaveError,     setItemSaveError]     = useState({})

  // Pick list state
  const [checkedItems,      setCheckedItems]      = useState(new Set())
  const [collapsedSections, setCollapsedSections] = useState(new Set())

  // Add item
  const [showAddItem,   setShowAddItem]   = useState(false)
  const [addSearch,     setAddSearch]     = useState('')
  const [addResults,    setAddResults]    = useState([])
  const [addingProduct, setAddingProduct] = useState(null)
  const [addQty,        setAddQty]        = useState('')
  const [addUnitId,     setAddUnitId]     = useState('')
  const [addUnits,      setAddUnits]      = useState([])
  const [addingSaving,  setAddingSaving]  = useState(false)
  const debouncedAddSearch = useDebounce(addSearch, 300)

  // Regular PO editing (non-commissary)
  const [editingItem, setEditingItem] = useState(null)
  const [editQty,     setEditQty]     = useState('')

  // Polling refs
  const pollRef       = useRef(null)
  const editingRef    = useRef(new Set()) // track which item ids are being edited

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchOrder = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    setError(null)
    try {
      const res = await axios.get(`/api/purchase-orders/${id}`)
      setOrder(prev => {
        if (!prev) return res.data
        // Merge — don't overwrite items currently being edited
        const mergedItems = res.data.items?.map(remoteItem => {
          if (editingRef.current.has(remoteItem.id)) {
            // Keep local version of item being edited
            const localItem = prev.items?.find(i => i.id === remoteItem.id)
            return localItem || remoteItem
          }
          return remoteItem
        })
        return { ...res.data, items: mergedItems }
      })
    } catch (e) {
      if (!silent) setError('Order not found.')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [id])

  // ── Initial load ───────────────────────────────────────────────────────────
  useEffect(() => { fetchOrder() }, [fetchOrder])

  // ── Polling with visibility guard ──────────────────────────────────────────
  const startPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(() => {
      fetchOrder(true) // silent poll — no loading spinner
    }, POLL_INTERVAL)
  }, [fetchOrder])

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => {
    startPolling()

    const handleVisibilityChange = () => {
      if (document.hidden) {
        stopPolling()
      } else {
        fetchOrder(true) // immediate refresh on tab focus
        startPolling()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      stopPolling()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [startPolling, stopPolling, fetchOrder])

  // ── Optimistic item update ─────────────────────────────────────────────────
  const updateItemLocally = (itemId, changes) => {
    setOrder(prev => ({
      ...prev,
      items: prev.items.map(item =>
        item.id === itemId ? { ...item, ...changes } : item
      )
    }))
  }

  // ── Short toggle — optimistic, no refresh ─────────────────────────────────
  const handleToggleShort = async (item) => {
    const newShort = !item.is_short
    // Update locally first
    updateItemLocally(item.id, { is_short: newShort })

    setSavingItems(prev => new Set(prev).add(item.id))
    try {
      await axios.put(`/api/purchase-order-items/${item.id}`, { is_short: newShort })
    } catch (e) {
      // Revert on failure
      updateItemLocally(item.id, { is_short: item.is_short })
      setItemSaveError(prev => ({ ...prev, [item.id]: 'Failed to save' }))
      setTimeout(() => setItemSaveError(prev => { const n = {...prev}; delete n[item.id]; return n }), 3000)
    } finally {
      setSavingItems(prev => { const n = new Set(prev); n.delete(item.id); return n })
    }
  }

  // ── Qty save — optimistic on blur, no refresh ─────────────────────────────
  const handleQtyBlur = async (item, newQty) => {
    const parsed = parseFloat(newQty)
    if (isNaN(parsed) || parsed === parseFloat(item.order_quantity)) {
      editingRef.current.delete(item.id)
      setEditingItem(null)
      return
    }

    // Update locally first
    updateItemLocally(item.id, {
      order_quantity:    parsed,
      original_quantity: item.original_quantity ?? item.order_quantity,
      edited_by:         'you',
      edited_at:         new Date().toISOString(),
    })
    editingRef.current.delete(item.id)
    setEditingItem(null)

    setSavingItems(prev => new Set(prev).add(item.id))
    try {
      await axios.put(`/api/purchase-order-items/${item.id}`, { order_quantity: parsed })
    } catch (e) {
      // Revert on failure
      updateItemLocally(item.id, { order_quantity: item.order_quantity })
      setItemSaveError(prev => ({ ...prev, [item.id]: 'Failed to save' }))
      setTimeout(() => setItemSaveError(prev => { const n = {...prev}; delete n[item.id]; return n }), 3000)
    } finally {
      setSavingItems(prev => { const n = new Set(prev); n.delete(item.id); return n })
    }
  }

  // ── Regular PO item save (non-commissary, still uses old pattern) ──────────
  const handleSaveItem = async (itemId) => {
    try {
      await axios.put(`/api/purchase-order-items/${itemId}`, { order_quantity: parseFloat(editQty) })
      setEditingItem(null)
      fetchOrder()
    } catch (e) {
      console.error('Failed to update item', e)
    }
  }

  const handleDeleteItem = async (itemId) => {
    if (!confirm('Remove this item?')) return
    try {
      await axios.delete(`/api/purchase-order-items/${itemId}`)
      fetchOrder()
    } catch (e) {
      console.error('Failed to delete item', e)
    }
  }

  const handleDeleteOrder = async () => {
    if (!confirm('Delete this order permanently?')) return
    try {
      await axios.delete(`/api/purchase-orders/${id}`)
      navigate('/orders/history')
    } catch (e) {
      console.error('Failed to delete order', e)
    }
  }

  const handleStatusChange = async (newStatus) => {
    const messages = {
      submitted: 'Submit this order?',
      received:  'Mark this order as received?',
      fulfilled: 'Mark this order as fulfilled?',
      draft:     'Reopen this order as a draft?',
    }
    if (!confirm(messages[newStatus] || `Mark as ${newStatus}?`)) return
    setSaving(true)
    try {
      await axios.put(`/api/purchase-orders/${id}`, { status: newStatus })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
      fetchOrder()
    } catch (e) {
      console.error('Failed to update status', e)
    } finally {
      setSaving(false)
    }
  }

  const toggleCheck = (itemId) => {
    setCheckedItems(prev => {
      const next = new Set(prev)
      next.has(itemId) ? next.delete(itemId) : next.add(itemId)
      return next
    })
  }

  const toggleSection = (sectionId) => {
    setCollapsedSections(prev => {
      const next = new Set(prev)
      next.has(sectionId) ? next.delete(sectionId) : next.add(sectionId)
      return next
    })
  }

  // Product search for add item
  useEffect(() => {
    if (!debouncedAddSearch || debouncedAddSearch.length < 2) { setAddResults([]); return }
    axios.get('/api/products', { params: { search: debouncedAddSearch, per_page: 8 } })
      .then(res => setAddResults(res.data.products || []))
      .catch(() => setAddResults([]))
  }, [debouncedAddSearch])

  const handleSelectAddProduct = async (product) => {
    setAddingProduct(product)
    setAddSearch('')
    setAddResults([])
    setAddQty('')
    setAddUnitId('')
    // Load product units — base unit + unit conversions
    try {
      const res = await axios.get(`/api/products/${product.id}`)
      const convUnits = res.data.unit_conversions?.map(u => ({
        id:   u.from_unit_id,
        name: u.from_unit,
      })) || []
      const baseUnit = { id: res.data.base_unit_id, name: res.data.base_unit }
      const seen = new Set()
      const units = [baseUnit, ...convUnits].filter(u => {
        if (seen.has(u.id)) return false
        seen.add(u.id)
        return true
      })
      setAddUnits(units)
      // Default to first unit (base unit)
      setAddUnitId(String(units[0]?.id || ''))
    } catch (e) {
      setAddUnits([])
    }
  }

  const handleAddItem = async () => {
    if (!addingProduct || !addQty) return
    setAddingSaving(true)
    try {
      await axios.post(`/api/purchase-orders/${id}/items`, {
        product_id:     addingProduct.id,
        order_quantity: parseFloat(addQty),
        unit_id:        addUnitId ? parseInt(addUnitId) : null,
      })
      setShowAddItem(false)
      setAddSearch('')
      setAddResults([])
      setAddingProduct(null)
      setAddQty('')
      setAddUnitId('')
      setAddUnits([])
      fetchOrder()
    } catch (e) {
      console.error('Failed to add item', e)
    } finally {
      setAddingSaving(false)
    }
  }

  const handleExportCSV = () => {
    if (!order) return
    const rows = [
      ['Product', 'Vendor Code', 'Quantity', 'Unit'],
      ...order.items.map(i => [i.product_name, i.vendor_code || '', i.order_quantity, i.order_unit || ''])
    ]
    const csv  = rows.map(r => r.map(v => `"${v}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `order-${order.vendor_name}-${order.order_date}.csv`.replace(/\s+/g, '-')
    a.click()
    URL.revokeObjectURL(url)
  }

  if (loading) return <div className="spinner">Loading order...</div>
  if (error)   return <div className="page"><div className="alert alert-error">{error}</div></div>
  if (!order)  return null

  const isDraft     = order.status === 'draft'
  const isSubmitted = order.status === 'submitted'
  const canEdit     = isManager || (isCommUser && order.is_commissary)
  const canDelete   = isAdmin
  const isEditable  = isDraft || (isSubmitted && (isManager || ((isComm || isCommGM) && order.is_commissary)))

  const commCols = isEditable
    ? (isManager || canDelete ? '40px 1fr 80px 80px 50px 70px' : '40px 1fr 80px 80px 50px')
    : canDelete ? '40px 1fr 80px 80px 70px' : '40px 1fr 80px 80px'
  const poCols = isEditable
    ? '1fr 120px 80px 80px 70px'
    : '1fr 120px 80px 80px'

  const renderItemRow = (item, isComm) => {
    const isChecked    = checkedItems.has(item.id)
    const isSaving     = savingItems.has(item.id)
    const hasError     = itemSaveError[item.id]
    const isEditingQty = editingItem === item.id

    return (
      <div key={item.id}
        className={`order-row ${isChecked ? 'order-row-checked' : ''} ${item.is_short ? 'order-row-short' : ''}`}
        style={{ gridTemplateColumns: isComm ? commCols : poCols }}>

        {isComm && (
          <div className="order-cell order-cell-check no-print">
            <input type="checkbox" checked={isChecked} onChange={() => toggleCheck(item.id)} />
          </div>
        )}

        <div className="order-cell order-cell-name">
          <span className="order-product-name">{item.product_name}</span>
          {item.is_short && <span className="order-short-badge">short</span>}
          {item.edited_by && !item.is_short && (
            <span className="order-edited-badge"
              title={`Edited by ${item.edited_by}${item.edited_at ? ' · ' + new Date(item.edited_at).toLocaleString() : ''}`}>
              edited
            </span>
          )}
          {isSaving && <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginLeft: '0.3rem' }}>saving…</span>}
          {hasError && <span style={{ fontSize: '0.65rem', color: 'var(--error)', marginLeft: '0.3rem' }}>⚠ {hasError}</span>}
        </div>

        {!isComm && (
          <div className="order-cell order-cell-code mono">{item.vendor_code || '—'}</div>
        )}

        <div className="order-cell order-cell-qty">
          {isComm && isEditable ? (
            // Commissary — always-visible input, saves on blur
            <NumericInput
              className="input order-qty-input"
              defaultValue={item.order_quantity}
              onFocus={() => {
                editingRef.current.add(item.id)
                setEditingItem(item.id)
              }}
              onBlur={e => handleQtyBlur(item, e.target.value)}
              onKeyDown={e => e.key === 'Enter' && e.target.blur()}
              style={{ opacity: item.is_short ? 0.5 : 1 }}
            />
          ) : isEditingQty ? (
            <NumericInput
              className="input order-qty-input"
              value={editQty} autoFocus
              onChange={e => setEditQty(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter')  handleSaveItem(item.id)
                if (e.key === 'Escape') setEditingItem(null)
              }} />
          ) : (
            <div style={{ textAlign: 'right' }}>
              <span className="order-qty"
                style={{ cursor: isEditable && !isComm ? 'pointer' : 'default' }}
                onClick={() => {
                  if (!isEditable || isComm) return
                  setEditingItem(item.id)
                  setEditQty(item.order_quantity)
                }}>
                {item.order_quantity}
              </span>
              {item.original_quantity != null &&
               parseFloat(item.original_quantity) !== parseFloat(item.order_quantity) && (
                <span className="order-original-qty">was {item.original_quantity}</span>
              )}
            </div>
          )}
        </div>

        <div className="order-cell order-cell-unit">{item.order_unit || '—'}</div>

        {/* Short toggle — commissary only */}
        {isComm && isEditable && (
          <div className="order-cell order-cell-short no-print">
            <button
              className={`short-btn ${item.is_short ? 'short-btn-active' : ''}`}
              title={item.is_short ? 'Clear short' : 'Mark short'}
              disabled={isSaving}
              onClick={() => handleToggleShort(item)}>
              {item.is_short ? '⚠' : '○'}
            </button>
          </div>
        )}

        {/* Edit/delete actions */}
        {isEditable && !isComm && (
          <div className="order-cell order-cell-actions no-print">
            {isEditingQty ? (
              <>
                <button className="btn btn-primary btn-sm" onClick={() => handleSaveItem(item.id)}>✓</button>
                <button className="btn btn-ghost btn-sm" onClick={() => setEditingItem(null)}>✕</button>
              </>
            ) : canDelete ? (
              <button className="btn btn-ghost btn-sm" style={{ color: 'var(--error)' }}
                onClick={() => handleDeleteItem(item.id)}>✕</button>
            ) : null}
          </div>
        )}

        {/* Admin delete on commissary items */}
        {isComm && canDelete && (
          <div className="order-cell order-cell-actions no-print">
            <button className="btn btn-ghost btn-sm" style={{ color: 'var(--error)' }}
              onClick={() => handleDeleteItem(item.id)}>✕</button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="page order-detail-page">

      {/* Header */}
      <div className="page-header no-print">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button className="btn btn-ghost" onClick={() => navigate('/orders/history')}>← Back</button>
          <div>
            <h1 className="page-title">{order.vendor_name}</h1>
            <p className="page-subtitle">{order.location_name} · {formatDate(order.order_date)}</p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {saved && <span className="save-confirm">Saved ✓</span>}
          <span className={`badge ${STATUS_BADGE[order.status]}`}>
            {order.status.charAt(0).toUpperCase() + order.status.slice(1)}
          </span>
          <span className={`badge ${order.is_commissary ? 'badge-warning' : 'badge-info'}`}>
            {order.is_commissary ? 'Commissary' : 'Purchase'}
          </span>
          <button className="btn btn-secondary" onClick={handleExportCSV}>CSV</button>
          <button className="btn btn-secondary" onClick={() => window.print()}>Print</button>
          {isDraft && canEdit && (
            <button className="btn btn-primary" disabled={saving}
              onClick={() => handleStatusChange('submitted')}>Submit</button>
          )}
          {isSubmitted && isManager && !order.is_commissary && (
            <button className="btn btn-primary" disabled={saving}
              onClick={() => handleStatusChange('received')}>Mark Received</button>
          )}
          {isSubmitted && (isCommGM || isAdmin) && order.is_commissary && (
            <button className="btn btn-primary" disabled={saving}
              onClick={() => handleStatusChange('fulfilled')}>Mark Fulfilled</button>
          )}
          {!isDraft && isAdmin && (
            <button className="btn btn-secondary" disabled={saving}
              onClick={() => handleStatusChange('draft')}>Reopen</button>
          )}
          {canDelete && (
            <button className="btn btn-ghost" style={{ color: 'var(--error)' }}
              onClick={handleDeleteOrder}>Delete</button>
          )}
        </div>
      </div>

      {/* Print header */}
      <div className="print-only order-print-header">
        <h2>{order.vendor_name}</h2>
        <p>{order.location_name} · {formatDate(order.order_date)}</p>
        {order.expected_date && <p>Expected: {formatDate(order.expected_date)}</p>}
        <p>Status: {order.status}</p>
      </div>

      {/* Expected date + notes */}
      {(isManager && (isDraft || isSubmitted)) || order.expected_date || order.notes ? (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <div className="card-body" style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
            {isManager && (
              <div className="form-group" style={{ margin: 0 }}>
                <label className="form-label">Expected Delivery Date</label>
                <input className="input" type="date" style={{ width: '180px' }}
                  defaultValue={toDateInputValue(order.expected_date)}
                  onBlur={async e => {
                    const current = toDateInputValue(order.expected_date)
                    if (e.target.value !== current) {
                      await axios.put(`/api/purchase-orders/${id}`, { expected_date: e.target.value || null })
                      fetchOrder()
                    }
                  }} />
              </div>
            )}
            {order.notes && (
              <div style={{ flex: 1, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                <span style={{ fontWeight: 600, color: 'var(--text-muted)', fontSize: '0.7rem', textTransform: 'uppercase' }}>Notes</span>
                <p style={{ margin: '0.2rem 0 0' }}>{order.notes}</p>
              </div>
            )}
          </div>
        </div>
      ) : null}

      {/* Line items */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">{order.items?.length || 0} items</h2>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            {order.is_commissary && (
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                Auto-saves · syncs every 30s
              </span>
            )}
            {isDraft && isManager && (
              <button className="btn btn-secondary btn-sm"
                onClick={() => setShowAddItem(s => !s)}>
                {showAddItem ? 'Cancel' : '+ Add Item'}
              </button>
            )}
          </div>
        </div>

        {/* Add item search */}
        {showAddItem && (
          <div style={{ padding: '0.75rem 1.25rem', borderBottom: '1px solid var(--border)' }}>
            {!addingProduct ? (
              <div>
                <input className="input" placeholder="Search products..."
                  value={addSearch} autoFocus
                  onChange={e => setAddSearch(e.target.value)} />
                {addResults.length > 0 && (
                  <div className="product-search-results" style={{ marginTop: '0.5rem' }}>
                    {addResults.map(p => (
                      <button key={p.id} className="product-search-result"
                        onClick={() => handleSelectAddProduct(p)}>
                        <span>{p.name}</span>
                        <span className="result-meta">{p.category_name} · {p.base_unit}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                <span style={{ fontWeight: 500, fontSize: '0.85rem' }}>{addingProduct.name}</span>
                <NumericInput
                  className="input"
                  placeholder="Qty"
                  value={addQty}
                  autoFocus
                  style={{ width: '80px' }}
                  onChange={e => setAddQty(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAddItem()}
                />
                {addUnits.length > 0 && (
                  <select className="input" style={{ width: '120px' }}
                    value={addUnitId}
                    onChange={e => setAddUnitId(e.target.value)}>
                    {addUnits.map(u => (
                      <option key={u.id} value={u.id}>{u.name}</option>
                    ))}
                  </select>
                )}
                <button className="btn btn-primary btn-sm"
                  onClick={handleAddItem} disabled={addingSaving || !addQty}>
                  {addingSaving ? 'Adding...' : 'Add'}
                </button>
                <button className="btn btn-ghost btn-sm"
                  onClick={() => { setAddingProduct(null); setAddQty(''); setAddUnitId(''); setAddUnits([]) }}>
                  ← Back
                </button>
              </div>
            )}
          </div>
        )}

        {order.is_commissary && order.sections?.length > 0 ? (
          <>
            <div className="order-row order-row-header" style={{ gridTemplateColumns: commCols }}>
              <div className="order-cell no-print" />
              <div className="order-cell">Product</div>
              <div className="order-cell order-cell-qty">Qty</div>
              <div className="order-cell order-cell-unit">Unit</div>
              {isEditable && <div className="order-cell no-print" />}
              {isEditable && isManager && <div className="order-cell no-print" />}
            </div>
            {order.sections.map(section => {
              const sectionItems = order.items?.filter(i => i.comm_section_id === section.id) || []
              if (!sectionItems.length) return null
              const isCollapsed  = collapsedSections.has(section.id)
              const checkedCount = sectionItems.filter(i => checkedItems.has(i.id)).length
              return (
                <div key={section.id}>
                  <div className="order-section-header"
                    style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                    onClick={() => toggleSection(section.id)}>
                    <span>{section.name}</span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.65rem', opacity: 0.8 }}>
                      {checkedCount > 0 && <span>{checkedCount}/{sectionItems.length} ✓</span>}
                      <span>{isCollapsed ? '▶' : '▼'}</span>
                    </span>
                  </div>
                  {!isCollapsed && sectionItems.map(item => renderItemRow(item, true))}
                </div>
              )
            })}
          </>
        ) : (
          <>
            <div className="order-row order-row-header" style={{ gridTemplateColumns: poCols }}>
              <div className="order-cell">Product</div>
              <div className="order-cell order-cell-code">Vendor Code</div>
              <div className="order-cell order-cell-qty">Qty</div>
              <div className="order-cell order-cell-unit">Unit</div>
              {isEditable && <div className="order-cell no-print" />}
            </div>
            {order.items?.length === 0 ? (
              <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                No items on this order.
              </div>
            ) : order.items?.map(item => renderItemRow(item, false))}
          </>
        )}
      </div>
    </div>
  )
}
