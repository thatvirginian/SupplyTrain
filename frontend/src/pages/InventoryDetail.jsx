import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../App.jsx'
import { formatDate } from '../utils/dateUtils.js'
import './catalog.css'
import './order-history.css'
import './inventory-detail.css'

export default function InventoryDetail() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const { isAdmin, isManager } = useAuth()

  const [inventory, setInventory] = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)

  // Grouped by category for display
  const [grouped,   setGrouped]   = useState({})

  // Inline editing
  const [editingItem,     setEditingItem]     = useState(null)
  const [editQty,         setEditQty]         = useState('')
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

  const handleCorrect = async (item) => {
    setSaving(true)
    try {
      await axios.put(`/api/inventory-submissions/${id}/items/${item.id}`, {
        base_quantity:    parseFloat(editQty),
        correction_notes: correctionNotes || null,
      })
      setEditingItem(null)
      setEditQty('')
      setCorrectionNotes('')
      fetchInventory()
    } catch (e) {
      console.error('Failed to correct item', e)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm('Delete this inventory? This cannot be undone.')) return
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
      ['Product', 'Category', 'Quantity', 'Base Unit', 'Par', 'Par Unit', 'Vendor Code'],
      ...(inventory.items || []).map(i => [
        i.product_name,
        i.category || '',
        i.base_quantity != null ? parseFloat(i.base_quantity) : '',
        i.base_unit || '',
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
              <div key={item.id} className="inv-detail-row">
                <div className="inv-detail-name">
                  <span className="inv-product-name">{item.product_name}</span>
                  {item.corrected_by && (
                    <span className="inv-corrected-badge"
                      title={`Corrected by ${item.corrected_by}${item.correction_notes ? ' — ' + item.correction_notes : ''}`}>
                      corrected
                    </span>
                  )}
                  {item.vendor_code && (
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: '0.4rem' }}>
                      {item.vendor_code}
                    </span>
                  )}
                </div>

                <div className="inv-detail-qty">
                  {editingItem === item.id ? (
                    <div className="inv-edit-wrap">
                      <input className="input" type="number" step="any" min="0"
                        value={editQty} autoFocus style={{ width: '90px' }}
                        onChange={e => setEditQty(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === 'Enter')  handleCorrect(item)
                          if (e.key === 'Escape') setEditingItem(null)
                        }} />
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{item.base_unit}</span>
                    </div>
                  ) : (
                    <span className="inv-qty-value"
                      style={{ cursor: isManager ? 'pointer' : 'default' }}
                      onClick={() => {
                        if (!isManager) return
                        setEditingItem(item.id)
                        setEditQty(item.base_quantity != null ? parseFloat(item.base_quantity) : '')
                        setCorrectionNotes('')
                      }}
                      title={isManager ? 'Click to correct' : ''}>
                      {formatQty(item.base_quantity, item.base_unit)}
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

                {isManager && (
                  <div className="inv-detail-actions no-print">
                    {editingItem === item.id ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                        <input className="input" placeholder="Reason (optional)"
                          value={correctionNotes} style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem' }}
                          onChange={e => setCorrectionNotes(e.target.value)} />
                        <div style={{ display: 'flex', gap: '0.3rem' }}>
                          <button className="btn btn-primary btn-sm"
                            onClick={() => handleCorrect(item)} disabled={saving}>✓</button>
                          <button className="btn btn-ghost btn-sm"
                            onClick={() => setEditingItem(null)}>✕</button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
