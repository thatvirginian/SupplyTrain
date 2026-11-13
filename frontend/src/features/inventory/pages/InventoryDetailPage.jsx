import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import { formatDate } from '../../../core/utils/dateUtils.js'
import '../../../core/styles/shared-ui.css'
import '../../../core/styles/order-and-print.css'
import './InventoryDetailPage.css'

export default function InventoryDetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const { isAdmin, isGM } = useAuth()
  // Corrections and deletes are admin / store GM only (matches gm_or_admin_required)
  const isManager = isAdmin || isGM

  const [inventory, setInventory] = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)

  // Grouped by category for display
  const [grouped,   setGrouped]   = useState({})

  // Inline editing
  const [editingItem,     setEditingItem]     = useState(null)
  const [editLines,       setEditLines]       = useState({})   // unit_id -> typed amount
  const [correctionNotes, setCorrectionNotes] = useState('')
  const [saving,          setSaving]          = useState(false)

  const fetchInventory = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.get(`/api/inventory-submissions/${id}`)
      setInventory(res.data)

      // Group items by category
      const groups = {}
      res.data.items?.forEach(item => {
        const cat = item.category || 'Uncategorized'
        if (!groups[cat]) groups[cat] = []
        groups[cat].push(item)
      })
      setGrouped(groups)
    } catch (e) {
      setError('Inventory not found.')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetchInventory() }, [fetchInventory])


  const formatQty = (qty, unit) => {
    if (qty == null) return '—'
    return `${parseFloat(qty).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${unit || ''}`
  }

  // The lines this inventory saved for a product, exactly as counted
  const linesFor = (item) =>
    (inventory?.entries || []).filter(e => e.product_id === item.product_id)

  // "2 Case + 5 lb" when the count was not simply typed in the base unit
  const countedAs = (item) => {
    const lines = linesFor(item)
    if (lines.length === 0) return ''
    if (lines.length === 1 && lines[0].unit_id === item.base_unit_id) return ''
    return lines.map(l => formatQty(l.quantity, l.unit_name).trim()).join(' + ')
  }

  // Correcting one product in place, the way it was counted: one box per unit
  // (the units it was counted in, then the template's other units). The server
  // sends these as item.unit_options, each with today's factor to the base unit.
  const startEditing = (item) => {
    const typed = {}
    linesFor(item).forEach(l => { typed[l.unit_id] = String(parseFloat(l.quantity)) })
    const lines = {}
    ;(item.unit_options || []).forEach(o => { lines[o.unit_id] = typed[o.unit_id] ?? '' })
    setEditingItem(item.product_id)
    setEditLines(lines)
    setCorrectionNotes('')
  }

  const cancelEditing = () => { setEditingItem(null); setEditLines({}) }

  // Live total in the base unit; null when a filled-in unit has no conversion
  const editTotal = (item) => {
    let total = 0
    for (const o of item.unit_options || []) {
      const v = editLines[o.unit_id]
      if (v === '' || v == null) continue
      const n = parseFloat(v)
      if (isNaN(n)) return null
      if (!o.to_base) return null
      total += n * o.to_base
    }
    return total
  }

  const handleCorrect = async (item) => {
    const lines = (item.unit_options || [])
      .map(o => ({ unit_id: o.unit_id, quantity: editLines[o.unit_id] }))
      .filter(l => l.quantity !== '' && l.quantity != null)
      .map(l => ({ ...l, quantity: parseFloat(l.quantity) }))
    if (lines.length === 0) { alert('Enter at least one amount.'); return }
    if (lines.some(l => isNaN(l.quantity) || l.quantity < 0)) { alert('Amounts must be numbers, 0 or more.'); return }
    setSaving(true)
    try {
      await axios.put(`/api/inventory-submissions/${id}/products/${item.product_id}`, {
        lines,
        correction_notes: correctionNotes || null,
      })
      cancelEditing()
      setCorrectionNotes('')
      fetchInventory()
    } catch (e) {
      console.error('Failed to correct item', e)
      alert(e.response?.data?.error || 'Could not save the correction.')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    const fromSheet = inventory?.source === 'count_sheet'
    const message = fromSheet
      ? 'Delete this inventory? Its purchase orders are not affected. ' +
        "The day's count goes back to the previous inventory for that day, if there is one. This cannot be undone."
      : "Delete this inventory? The day's count goes back to the previous inventory for that day, if there is one. This cannot be undone."
    if (!confirm(message)) return
    try {
      await axios.delete(`/api/inventory-submissions/${id}`)
      navigate('/inventory/history')
    } catch (e) {
      console.error('Failed to delete inventory', e)
    }
  }

  const handleExportCSV = () => {
    if (!inventory) return
    const rows = [
      ['Product', 'Category', 'Quantity', 'Base Unit', 'Counted As', "Day's Count", 'Par', 'Par Unit', 'Vendor Code'],
      ...(inventory.items || []).map(i => [
        i.product_name,
        i.category || '',
        i.base_quantity != null ? parseFloat(i.base_quantity) : '',
        i.base_unit || '',
        countedAs(i) || formatQty(i.base_quantity, i.base_unit).trim(),
        i.is_day_count ? 'Yes' : 'No',
        i.par_qty != null ? parseFloat(i.par_qty) : '',
        i.par_unit || '',
        i.vendor_code || '',
      ])
    ]
    const csv  = rows.map(r => r.map(v => `"${v}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `inventory-${inventory.location_name}-${inventory.count_date}.csv`.replace(/\s+/g, '-')
    a.click()
    URL.revokeObjectURL(url)
  }

  if (loading) return <div className="spinner">Loading inventory...</div>
  if (error)   return <div className="page"><div className="alert alert-error">{error}</div></div>
  if (!inventory) return null

  const isFromCountSheet = inventory.source === 'count_sheet'
  const isSubmitted      = inventory.status === 'submitted'
  // Changing a submitted inventory: the server decides who may (core/auth.py,
  // INVENTORY_EDIT_ROLES) and says so in can_edit. A draft is edited on its entry sheet.
  const canCorrect       = isSubmitted && !!inventory.can_edit

  return (
    <div className="page">
      {/* Header */}
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button className="btn btn-ghost" onClick={() => navigate('/inventory/history')}>← Back</button>
          <div>
            <h1 className="page-title">{inventory.location_name}</h1>
            <p className="page-subtitle">
              {formatDate(inventory.count_date)} ·{' '}
              <span className={`badge ${inventory.source === 'count_sheet' ? 'badge-info' : 'badge-warning'}`}
                style={{ fontSize: '0.65rem' }}>
                {isFromCountSheet ? 'Count Sheet' : 'Manual'}
              </span>
              {inventory.template_name && ` · ${inventory.template_name}`}
            </p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {isFromCountSheet && inventory.sheet_submission_id && (
            <button className="btn btn-secondary"
              onClick={() => navigate(`/count-sheet/${inventory.sheet_submission_id}`)}>
              View Count Sheet
            </button>
          )}
          {canCorrect && (
            <button className="btn btn-primary"
              onClick={() => navigate(`/inventory/entry/${inventory.id}`)}>
              Edit Counts
            </button>
          )}
          <button className="btn btn-secondary" onClick={handleExportCSV}>CSV</button>
          <button className="btn btn-secondary" onClick={() => window.print()}>Print</button>
          {isManager && (
            <button className="btn btn-ghost" style={{ color: 'var(--error)' }}
              onClick={handleDelete}>Delete</button>
          )}
        </div>
      </div>

      {/* Summary */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        <div className="card" style={{ padding: '0.75rem 1.25rem', flex: '1', minWidth: '120px' }}>
          <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Products</div>
          <div style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text-primary)' }}>{inventory.items?.length || 0}</div>
        </div>
        <div className="card" style={{ padding: '0.75rem 1.25rem', flex: '1', minWidth: '120px' }}>
          <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Entered by</div>
          <div style={{ fontSize: '0.85rem', fontWeight: 500, color: 'var(--text-primary)' }}>
            {inventory.submitted_by || '—'}
          </div>
        </div>
        <div className="card" style={{ padding: '0.75rem 1.25rem', flex: '1', minWidth: '120px' }}>
          <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Categories</div>
          <div style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text-primary)' }}>{Object.keys(grouped).length}</div>
        </div>
      </div>

      {/* Items grouped by category */}
      <div className="card">
        {/* Header row */}
        <div className="inv-detail-header">
          <div className="inv-detail-name">Product</div>
          <div className="inv-detail-qty">On Hand</div>
          <div className="inv-detail-par">Par</div>
          {isManager && <div className="inv-detail-actions no-print" />}
        </div>

        {Object.entries(grouped).map(([category, items]) => (
          <div key={category}>
            <div className="inv-detail-category">{category}</div>
            {items.map(item => (
              <div key={item.product_id} className="inv-detail-row">
                <div className="inv-detail-name">
                  <span className="inv-product-name">{item.product_name}</span>
                  {item.corrected_by && (
                    <span className="inv-corrected-badge"
                      title={`Corrected by ${item.corrected_by}${item.correction_notes ? ' — ' + item.correction_notes : ''}`}>
                      corrected
                    </span>
                  )}
                  {isSubmitted && item.is_day_count === false && (
                    <span className="inv-replaced-badge"
                      title="A later inventory that day also counted this product. This number is kept here, but the later one is the day's count.">
                      replaced by later count
                    </span>
                  )}
                  {item.vendor_code && (
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: '0.4rem' }}>
                      {item.vendor_code}
                    </span>
                  )}
                </div>

                <div className="inv-detail-qty">
                  {(
                    <span className={`inv-qty-value ${editingItem === item.product_id ? 'inv-qty-editing' : ''}`}
                      style={{ cursor: canCorrect ? 'pointer' : 'default' }}
                      onClick={() => {
                        if (!canCorrect) return
                        if (editingItem === item.product_id) cancelEditing()
                        else startEditing(item)
                      }}
                      title={canCorrect ? 'Click to correct' : ''}>
                      {formatQty(item.base_quantity, item.base_unit)}
                      {countedAs(item) && (
                        <span className="inv-counted-as">{countedAs(item)}</span>
                      )}
                      {item.original_quantity != null && (
                        <span className="inv-original-qty">
                          was {formatQty(item.original_quantity, item.base_unit)}
                        </span>
                      )}
                    </span>
                  )}
                </div>

                <div className="inv-detail-par">
                  {item.par_qty != null
                    ? <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                        {formatQty(item.par_qty, item.par_unit)}
                      </span>
                    : <span style={{ color: 'var(--text-muted)' }}>—</span>
                  }
                </div>

                {isManager && <div className="inv-detail-actions no-print" />}

                {editingItem === item.product_id && (() => {
                  const total = editTotal(item)
                  return (
                    <div className="inv-edit-panel no-print">
                      <div className="inv-edit-units">
                        {(item.unit_options || []).map((o, idx) => (
                          <span key={o.unit_id} className="inv-edit-unit">
                            {idx > 0 && <span className="inv-edit-plus">+</span>}
                            <input className="input inv-edit-input" type="number" step="any" min="0"
                              autoFocus={idx === 0} value={editLines[o.unit_id] ?? ''}
                              onChange={e => setEditLines(l => ({ ...l, [o.unit_id]: e.target.value }))}
                              onKeyDown={e => {
                                if (e.key === 'Enter')  handleCorrect(item)
                                if (e.key === 'Escape') cancelEditing()
                              }} />
                            <span className="inv-edit-unit-name">{o.unit_name}</span>
                            {!o.to_base && <span className="inv-edit-noconv" title="No conversion to the base unit">!</span>}
                          </span>
                        ))}
                        <span className="inv-edit-total">
                          = {total == null ? '?' : formatQty(total, item.base_unit)}
                        </span>
                      </div>
                      <div className="inv-edit-actions">
                        <input className="input inv-edit-reason" placeholder="Reason (optional)"
                          value={correctionNotes}
                          onChange={e => setCorrectionNotes(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter') handleCorrect(item) }} />
                        <button className="btn btn-primary btn-sm"
                          onClick={() => handleCorrect(item)} disabled={saving}>
                          {saving ? 'Saving...' : 'Save'}
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={cancelEditing}>Cancel</button>
                      </div>
                    </div>
                  )
                })()}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
