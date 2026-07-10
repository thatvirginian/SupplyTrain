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
  open:      'badge-warning',
  accepted:  'badge-info',
  submitted: 'badge-info',
  shipped:   'badge-info',
  fulfilled: 'badge-success',
  cancelled: 'badge-error',
}

const POLL_INTERVAL = 30000

export default function OrderDetail() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const { isAdmin, isManager, isComm, isCommGM, isCommUser, isStore, isGM } = useAuth()

  const [order,   setOrder]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [saving,  setSaving]  = useState(false)
  const [saved,   setSaved]   = useState(false)

  // Per-item saving
  const [savingItems,   setSavingItems]   = useState(new Set())
  const [itemSaveError, setItemSaveError] = useState({})

  // Pick list
  const [checkedItems,      setCheckedItems]      = useState(new Set())
  const [collapsedSections, setCollapsedSections] = useState(new Set())

  // Receive mode (shipped state)
  const [receiveNotes,   setReceiveNotes]   = useState({})  // item.id → note
  const [fulfillNote,    setFulfillNote]    = useState('')
  const [fulfilling,     setFulfilling]     = useState(false)

  // Regular PO editing
  const [editingItem, setEditingItem] = useState(null)
  const [editQty,     setEditQty]     = useState('')

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

  // Polling
  const pollRef    = useRef(null)
  const editingRef = useRef(new Set())

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchOrder = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    setError(null)
    try {
      const res = await axios.get(`/api/purchase-orders/${id}`)
      setOrder(prev => {
        if (!prev) {
          // Initialize checkedItems from picked state on first load
          const picked = new Set(
            (res.data.items || []).filter(i => i.picked).map(i => i.id)
          )
          setCheckedItems(picked)
          return res.data
        }
        const mergedItems = res.data.items?.map(remoteItem => {
          if (editingRef.current.has(remoteItem.id)) {
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

  useEffect(() => { fetchOrder() }, [fetchOrder])

  // ── Polling ────────────────────────────────────────────────────────────────
  const startPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(() => fetchOrder(true), POLL_INTERVAL)
  }, [fetchOrder])

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])

  useEffect(() => {
    startPolling()
    const onVisibility = () => {
      if (document.hidden) { stopPolling() }
      else { fetchOrder(true); startPolling() }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => { stopPolling(); document.removeEventListener('visibilitychange', onVisibility) }
  }, [startPolling, stopPolling, fetchOrder])

  // ── Optimistic item update ─────────────────────────────────────────────────
  const updateItemLocally = (itemId, changes) => {
    setOrder(prev => ({
      ...prev,
      items: prev.items.map(item => item.id === itemId ? { ...item, ...changes } : item)
    }))
  }

  // ── Pick list checkbox — saves picked state ────────────────────────────────
  const handleToggleCheck = async (item) => {
    const newPicked = !checkedItems.has(item.id)
    setCheckedItems(prev => {
      const next = new Set(prev)
      newPicked ? next.add(item.id) : next.delete(item.id)
      return next
    })
    updateItemLocally(item.id, { picked: newPicked })
    try {
      await axios.put(`/api/purchase-order-items/${item.id}`, { picked: newPicked })
    } catch (e) {
      // Revert
      setCheckedItems(prev => {
        const next = new Set(prev)
        newPicked ? next.delete(item.id) : next.add(item.id)
        return next
      })
      updateItemLocally(item.id, { picked: item.picked })
    }
  }

  // ── Short toggle ───────────────────────────────────────────────────────────
  const handleToggleShort = async (item) => {
    const newShort = !item.is_short
    updateItemLocally(item.id, { is_short: newShort })
    setSavingItems(prev => new Set(prev).add(item.id))
    try {
      await axios.put(`/api/purchase-order-items/${item.id}`, { is_short: newShort })
    } catch (e) {
      updateItemLocally(item.id, { is_short: item.is_short })
      setItemSaveError(prev => ({ ...prev, [item.id]: 'Failed' }))
      setTimeout(() => setItemSaveError(prev => { const n = {...prev}; delete n[item.id]; return n }), 3000)
    } finally {
      setSavingItems(prev => { const n = new Set(prev); n.delete(item.id); return n })
    }
  }

  // ── Qty blur save ──────────────────────────────────────────────────────────
  const handleQtyBlur = async (item, newQty) => {
    const parsed = parseFloat(newQty)
    if (isNaN(parsed) || parsed === parseFloat(item.order_quantity)) {
      editingRef.current.delete(item.id)
      setEditingItem(null)
      return
    }
    updateItemLocally(item.id, { order_quantity: parsed, edited_by: 'you', edited_at: new Date().toISOString() })
    editingRef.current.delete(item.id)
    setEditingItem(null)
    setSavingItems(prev => new Set(prev).add(item.id))
    try {
      await axios.put(`/api/purchase-order-items/${item.id}`, { order_quantity: parsed })
    } catch (e) {
      updateItemLocally(item.id, { order_quantity: item.order_quantity })
    } finally {
      setSavingItems(prev => { const n = new Set(prev); n.delete(item.id); return n })
    }
  }

  // ── Receive item (shipped state) ───────────────────────────────────────────
  const handleReceiveItem = async (item, status) => {
    const current = item.received_status
    const newStatus = current === status ? null : status  // toggle off if same
    updateItemLocally(item.id, { received_status: newStatus })
    setSavingItems(prev => new Set(prev).add(item.id))
    try {
      await axios.put(`/api/purchase-order-items/${item.id}/receive`, {
        received_status: newStatus,
        received_note:   receiveNotes[item.id] || null,
      })
    } catch (e) {
      updateItemLocally(item.id, { received_status: current })
    } finally {
      setSavingItems(prev => { const n = new Set(prev); n.delete(item.id); return n })
    }
  }

  // ── Fulfill order ──────────────────────────────────────────────────────────
  const handleFulfill = async () => {
    if (!confirm('Mark this order as fulfilled? This cannot be undone.')) return
    setFulfilling(true)
    try {
      await axios.post(`/api/purchase-orders/${id}/fulfill`, { notes: fulfillNote || null })
      fetchOrder()
    } catch (e) {
      console.error('Failed to fulfill', e)
    } finally {
      setFulfilling(false)
    }
  }

  // ── Regular PO item save (non-commissary) ──────────────────────────────────
  const handleSaveItem = async (itemId) => {
    try {
      await axios.put(`/api/purchase-order-items/${itemId}`, { order_quantity: parseFloat(editQty) })
      setEditingItem(null)
      fetchOrder()
    } catch (e) { console.error('Failed to update item', e) }
  }

  const handleDeleteItem = async (itemId) => {
    if (!confirm('Remove this item?')) return
    try {
      await axios.delete(`/api/purchase-order-items/${itemId}`)
      fetchOrder()
    } catch (e) { console.error('Failed to delete item', e) }
  }

  const handleDeleteOrder = async () => {
    if (!confirm('Delete this order permanently?')) return
    try {
      await axios.delete(`/api/purchase-orders/${id}`)
      navigate('/orders/history')
    } catch (e) { console.error('Failed to delete order', e) }
  }

  const handleStatusChange = async (newStatus) => {
    const messages = {
      accepted:  'Accept this order? Store will no longer be able to edit it.',
      shipped:   'Mark this order as shipped?',
      open:      'Reopen this order? Store will be able to edit it again.',
      cancelled: 'Cancel this order?',
    }
    if (!confirm(messages[newStatus] || `Mark as ${newStatus}?`)) return
    setSaving(true)
    try {
      if (newStatus === 'accepted') {
        await axios.post(`/api/purchase-orders/${id}/accept`)
      } else if (newStatus === 'shipped') {
        await axios.post(`/api/purchase-orders/${id}/ship`)
      } else {
        await axios.put(`/api/purchase-orders/${id}`, { status: newStatus })
      }
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
      fetchOrder()
    } catch (e) { console.error('Failed to update status', e) }
    finally { setSaving(false) }
  }

  const toggleSection = (sectionId) => {
    setCollapsedSections(prev => {
      const next = new Set(prev)
      next.has(sectionId) ? next.delete(sectionId) : next.add(sectionId)
      return next
    })
  }

  // ── Product search for add item ────────────────────────────────────────────
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
    try {
      const res = await axios.get(`/api/products/${product.id}`)
      const convUnits = res.data.unit_conversions?.map(u => ({ id: u.from_unit_id, name: u.from_unit })) || []
      const baseUnit  = { id: res.data.base_unit_id, name: res.data.base_unit }
      const seen = new Set()
      const units = [baseUnit, ...convUnits].filter(u => { if (seen.has(u.id)) return false; seen.add(u.id); return true })
      setAddUnits(units)
      setAddUnitId(String(units[0]?.id || ''))
    } catch (e) { setAddUnits([]) }
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
      setShowAddItem(false); setAddSearch(''); setAddResults([])
      setAddingProduct(null); setAddQty(''); setAddUnitId(''); setAddUnits([])
      fetchOrder()
    } catch (e) { console.error('Failed to add item', e) }
    finally { setAddingSaving(false) }
  }

  if (loading) return <div className="spinner">Loading order...</div>
  if (error)   return <div className="page"><div className="alert alert-error">{error}</div></div>
  if (!order)  return null

  const isOpen      = order.status === 'open'
  const isAccepted  = order.status === 'accepted'
  const isShipped   = order.status === 'shipped'
  const isFulfilled = order.status === 'fulfilled'
  const canEdit     = isManager || (isCommUser && order.is_commissary)
  const canDelete   = isAdmin
  // Store/GM can edit when open, comm/comm_gm can edit when accepted, admin always
  const isEditable  = isAdmin
    || (isOpen && (isStore || isGM))
    || (isAccepted && (isComm || isCommGM))
  const canAccept   = isOpen && (isCommGM || isAdmin)
  const canShip     = isAccepted && (isCommGM || isAdmin)
  const canFulfill  = isShipped && (isStore || isManager || isAdmin)
  const canReceive  = isShipped

  const COL_GAP = '8px'
  const showCheckbox = !isFulfilled && !isShipped && !isOpen
  const commCols = isShipped   ? '1fr 80px 80px 80px 100px 70px'
    : isFulfilled  ? (canDelete ? '1fr 80px 80px 70px' : '1fr 80px 80px')
    : isOpen       ? (canDelete ? '1fr 80px 80px 70px' : '1fr 80px 80px')
    : isEditable   ? (isManager || canDelete ? '40px 1fr 80px 80px 50px 70px' : '40px 1fr 80px 80px 50px')
    : canDelete    ? '40px 1fr 80px 80px 70px' : '40px 1fr 80px 80px'
  const poCols = isEditable ? '1fr 120px 80px 80px 70px' : '1fr 120px 80px 80px'

  const formatDate2 = (d) => d ? new Date(d).toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
  }) : '—'

  // ── Item row renderer ──────────────────────────────────────────────────────
  const renderItemRow = (item, isComm) => {
    const isPicked   = checkedItems.has(item.id)
    const isSaving   = savingItems.has(item.id)
    const hasError   = itemSaveError[item.id]
    const isEditingQ = editingItem === item.id

    if (isShipped) {
      // ── Receive mode ───────────────────────────────────────────────────────
      return (
        <div key={item.id} className={`order-row ${item.received_status === 'returned' ? 'order-row-short' : ''}`}
          style={{ gridTemplateColumns: '1fr 80px 80px 80px 100px 40px' }}>
          <div className="order-cell order-cell-name">
            <span className="order-product-name">{item.product_name}</span>
            {item.is_short && <span className="order-short-badge">short</span>}
          </div>
          <div className="order-cell order-cell-qty" style={{ textAlign: 'right' }}>
            {item.order_quantity}
          </div>
          <div className="order-cell order-cell-unit">{item.order_unit || '—'}</div>
          <div className="order-cell" style={{ display: 'flex', gap: '4px' }}>
            <button
              className={`btn btn-sm ${item.received_status === 'received' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ fontSize: '0.65rem', padding: '0.2rem 0.4rem' }}
              onClick={() => handleReceiveItem(item, 'received')}>
              ✓
            </button>
            <button
              className={`btn btn-sm ${item.received_status === 'returned' ? 'btn-danger' : 'btn-secondary'}`}
              style={{ fontSize: '0.65rem', padding: '0.2rem 0.4rem' }}
              onClick={() => handleReceiveItem(item, 'returned')}>
              ↩
            </button>
          </div>
          <div className="order-cell">
            <input className="input" style={{ fontSize: '0.7rem', padding: '0.2rem 0.4rem' }}
              placeholder="Note..."
              value={receiveNotes[item.id] || ''}
              onChange={e => setReceiveNotes(prev => ({ ...prev, [item.id]: e.target.value }))}
              onBlur={async e => {
                if (item.received_status) {
                  await axios.put(`/api/purchase-order-items/${item.id}/receive`, {
                    received_status: item.received_status,
                    received_note:   e.target.value || null,
                  })
                }
              }} />
          </div>
          <div className="order-cell" style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            {item.received_status || ''}
          </div>
        </div>
      )
    }

    return (
      <div key={item.id}
        className={`order-row ${isPicked ? 'order-row-checked' : ''} ${item.is_short ? 'order-row-short' : ''}`}
        style={{ gridTemplateColumns: isComm ? commCols : poCols }}>

        {/* Checkbox moved to left for commissary pick list */}
        {isComm && showCheckbox && (
          <div className="order-cell order-cell-check no-print">
            <input type="checkbox" checked={isPicked} onChange={() => handleToggleCheck(item)} />
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

        {!isComm && <div className="order-cell order-cell-code mono">{item.vendor_code || '—'}</div>}

        <div className="order-cell order-cell-qty">
          {isComm && isEditable && !isFulfilled ? (
            <NumericInput className="input order-qty-input"
              defaultValue={item.order_quantity}
              onFocus={() => { editingRef.current.add(item.id); setEditingItem(item.id) }}
              onBlur={e => handleQtyBlur(item, e.target.value)}
              onKeyDown={e => e.key === 'Enter' && e.target.blur()}
              style={{ opacity: item.is_short ? 0.5 : 1 }} />
          ) : isEditingQ ? (
            <NumericInput className="input order-qty-input" value={editQty} autoFocus
              onChange={e => setEditQty(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter')  handleSaveItem(item.id)
                if (e.key === 'Escape') setEditingItem(null)
              }} />
          ) : (
            <div style={{ textAlign: 'right' }}>
              <span className="order-qty"
                style={{ cursor: isEditable && !isComm ? 'pointer' : 'default' }}
                onClick={() => { if (!isEditable || isComm) return; setEditingItem(item.id); setEditQty(item.order_quantity) }}>
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

        {/* Short toggle — accepted state only */}
        {isComm && isEditable && !isFulfilled && !isOpen && (
          <div className="order-cell order-cell-short no-print">
            <button className={`short-btn ${item.is_short ? 'short-btn-active' : ''}`}
              title={item.is_short ? 'Clear short' : 'Mark short'}
              disabled={isSaving}
              onClick={() => handleToggleShort(item)}>
              {item.is_short ? '⚠' : '○'}
            </button>
          </div>
        )}

        {/* Edit/delete — non-commissary */}
        {isEditable && !isComm && (
          <div className="order-cell order-cell-actions no-print">
            {isEditingQ ? (
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

        {/* Admin delete on commissary — not on fulfilled */}
        {isComm && canDelete && !isFulfilled && (
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
          <span className={`badge ${STATUS_BADGE[order.status] || 'badge-neutral'}`}>
            {order.status.charAt(0).toUpperCase() + order.status.slice(1)}
          </span>
          <span className={`badge ${order.is_commissary ? 'badge-warning' : 'badge-info'}`}>
            {order.is_commissary ? 'Commissary' : 'Purchase'}
          </span>
          <button className="btn btn-secondary" onClick={() => window.open(`/api/purchase-orders/${id}/pdf`, '_blank')}>
            Print PDF
          </button>
          <button className="btn btn-secondary" onClick={() => window.print()}>Print</button>

          {/* Status transitions */}
          {canAccept && (
            <button className="btn btn-primary" disabled={saving}
              onClick={() => handleStatusChange('accepted')}>Accept Order</button>
          )}
          {canShip && (
            <button className="btn btn-primary" disabled={saving}
              onClick={() => handleStatusChange('shipped')}>Mark Shipped</button>
          )}
          {canFulfill && !isCommGM && (
            <button className="btn btn-primary" disabled={fulfilling}
              onClick={handleFulfill}>
              {fulfilling ? 'Fulfilling...' : 'Mark Fulfilled'}
            </button>
          )}
          {!isOpen && isAdmin && (
            <button className="btn btn-secondary" disabled={saving}
              onClick={() => handleStatusChange('open')}>Reopen</button>
          )}
          {canDelete && (
            <button className="btn btn-ghost" style={{ color: 'var(--error)' }}
              onClick={handleDeleteOrder}>Delete</button>
          )}
        </div>
      </div>

      {/* Order meta */}
      <div className="card" style={{ marginBottom: '1rem', padding: '0.6rem 1rem' }}>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center', fontSize: '0.78rem' }}>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            <span style={{ color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.65rem', textTransform: 'uppercase' }}>ETA</span>
            {isManager && (isOpen || isAccepted) ? (
              <input className="input" type="date" style={{ width: '140px', padding: '0.2rem 0.4rem', fontSize: '0.75rem' }}
                defaultValue={toDateInputValue(order.expected_date)}
                onBlur={async e => {
                  const current = toDateInputValue(order.expected_date)
                  if (e.target.value !== current) {
                    await axios.put(`/api/purchase-orders/${id}`, { expected_date: e.target.value || null })
                    fetchOrder()
                  }
                }} />
            ) : (
              <span>{order.expected_date ? formatDate(order.expected_date) : '—'}</span>
            )}
          </div>

          {order.shipped_at && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <span style={{ color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.65rem', textTransform: 'uppercase' }}>Shipped</span>
              <span>{new Date(order.shipped_at).toLocaleDateString()}</span>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>by {order.shipped_by?.split('@')[0]}</span>
            </div>
          )}

          {order.fulfilled_at && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <span style={{ color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.65rem', textTransform: 'uppercase' }}>Fulfilled</span>
              <span>{new Date(order.fulfilled_at).toLocaleDateString()}</span>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>by {order.fulfilled_by?.split('@')[0]}</span>
            </div>
          )}

          {order.notes && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <span style={{ color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.65rem', textTransform: 'uppercase' }}>Note</span>
              <span style={{ color: 'var(--text-secondary)' }}>{order.notes}</span>
            </div>
          )}

          {canFulfill && (
            <input className="input" style={{ flex: 1, minWidth: '160px', maxWidth: '260px', padding: '0.2rem 0.5rem', fontSize: '0.75rem' }}
              placeholder="Fulfillment note..."
              value={fulfillNote}
              onChange={e => setFulfillNote(e.target.value)} />
          )}

        </div>
      </div>

      {/* Line items */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">{order.items?.length || 0} items</h2>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            {order.is_commissary && !isShipped && (
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                Auto-saves · syncs every 30s
              </span>
            )}
            {isShipped && (
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                ✓ Received &nbsp;·&nbsp; ↩ Returned
              </span>
            )}
            {isOpen && isManager && (
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
                <input className="input" placeholder="Search products..." value={addSearch} autoFocus
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
                <NumericInput className="input" placeholder="Qty" value={addQty} autoFocus
                  style={{ width: '80px' }}
                  onChange={e => setAddQty(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAddItem()} />
                {addUnits.length > 0 && (
                  <select className="input" style={{ width: '120px' }}
                    value={addUnitId} onChange={e => setAddUnitId(e.target.value)}>
                    {addUnits.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
                  </select>
                )}
                <button className="btn btn-primary btn-sm" onClick={handleAddItem} disabled={addingSaving || !addQty}>
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

        {/* Receive mode header */}
        {isShipped && (
          <div className="order-row order-row-header"
            style={{ gridTemplateColumns: '1fr 80px 80px 80px 100px 40px' }}>
            <div className="order-cell">Product</div>
            <div className="order-cell order-cell-qty">Qty</div>
            <div className="order-cell order-cell-unit">Unit</div>
            <div className="order-cell">Status</div>
            <div className="order-cell">Note</div>
            <div className="order-cell" />
          </div>
        )}

        {/* Commissary sections */}
        {order.is_commissary && order.sections?.length > 0 && !isShipped ? (
          <>
            <div className="order-row order-row-header" style={{ gridTemplateColumns: commCols }}>
              {showCheckbox && <div className="order-cell no-print" />}
              <div className="order-cell">Product</div>
              <div className="order-cell order-cell-qty">Qty</div>
              <div className="order-cell order-cell-unit">Unit</div>
              {isEditable && <div className="order-cell no-print" />}
              {(isEditable && isManager) || canDelete ? <div className="order-cell no-print" /> : null}
            </div>
            {order.sections.map(section => {
              const sectionItems = order.items?.filter(i => i.comm_section_id === section.id) || []
              if (!sectionItems.length) return null
              const isCollapsed  = collapsedSections.has(section.id)
              const pickedCount  = sectionItems.filter(i => checkedItems.has(i.id)).length
              return (
                <div key={section.id}>
                  <div className="order-section-header"
                    style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                    onClick={() => toggleSection(section.id)}>
                    <span>{section.name}</span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.65rem', opacity: 0.8 }}>
                      {pickedCount > 0 && <span>{pickedCount}/{sectionItems.length} ✓</span>}
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
            {!isShipped && (
              <div className="order-row order-row-header" style={{ gridTemplateColumns: order.is_commissary ? commCols : poCols }}>
                {order.is_commissary && showCheckbox && <div className="order-cell no-print" />}
                <div className="order-cell">Product</div>
                {!order.is_commissary && <div className="order-cell order-cell-code">Vendor Code</div>}
                <div className="order-cell order-cell-qty">Qty</div>
                <div className="order-cell order-cell-unit">Unit</div>
                {isEditable && <div className="order-cell no-print" />}
              </div>
            )}
            {order.items?.length === 0 ? (
              <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                No items on this order.
              </div>
            ) : order.items?.map(item => renderItemRow(item, order.is_commissary))}
          </>
        )}
      </div>
    </div>
  )
}
