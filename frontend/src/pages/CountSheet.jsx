import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../App.jsx'
import { toDateInputValue } from '../utils/dateUtils.js'
import { NumericInput } from '../components/NumericInput.jsx'
import './count-sheet.css'

export default function CountSheet() {
  const { submissionId } = useParams()
  const navigate         = useNavigate()
  const { isAdmin }      = useAuth()

  // ── State ──────────────────────────────────────────────────────────────────
  const [submission,  setSubmission]  = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)
  const [saving,      setSaving]      = useState(false)
  const [submitting,  setSubmitting]  = useState(false)
  const [saved,       setSaved]       = useState(false)

  // entries: { `${product_id}_${unit_id}`: quantity }
  const [entries, setEntries] = useState({})

  // Expected delivery date — defaults to count date + 1 day
  const [expectedDate, setExpectedDate] = useState('')

  const touchedRef = useRef(new Set())

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchSubmission = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.get(`/api/sheet-submissions/${submissionId}`)
      setSubmission(res.data)

      // Default expected date = count date + 1 day
      if (res.data.count_date) {
        const datePart = String(res.data.count_date).slice(0, 10)
        const d = new Date(`${datePart}T00:00:00`)
        d.setDate(d.getDate() + 1)
        setExpectedDate(d.toISOString().split('T')[0])
      }

      // Pre-populate entries from saved data — keyed by product_id_unit_id
      const saved = {}
      res.data.sections?.forEach(section => {
        section.items?.forEach(item => {
          item.count_units?.forEach(cu => {
            if (cu.saved_quantity != null) {
              saved[`${item.product_id}_${cu.unit_id}`] = String(cu.saved_quantity)
            }
          })
          // Also check item.entry for backwards compatibility
          if (item.entry?.quantity != null) {
            const key = `${item.product_id}_${item.entry.unit_id}`
            if (!saved[key]) saved[key] = String(item.entry.quantity)
          }
        })
      })
      setEntries(saved)

    } catch (e) {
      setError('Failed to load count sheet.')
    } finally {
      setLoading(false)
    }
  }, [submissionId])

  useEffect(() => { fetchSubmission() }, [fetchSubmission])

  // ── Entry change ───────────────────────────────────────────────────────────
  const handleChange = (productId, unitId, value) => {
    const key = `${productId}_${unitId}`
    setEntries(e => ({ ...e, [key]: value }))
    touchedRef.current.add(key)
  }

  // ── Order quantity calculation ─────────────────────────────────────────────
  const getOrderQty = (item) => {
    const par = item.par
    if (!par || !par.par_qty) return { qty: null, unit: null, needsConversion: false }

    const countUnitIds = (item.count_units || []).map(cu => cu.unit_id)
    const allMatchPar  = countUnitIds.every(id => id === par.unit_id)

    if (!allMatchPar) {
      return { qty: null, unit: par.unit_name, needsConversion: true }
    }

    let totalOnHand = 0
    item.count_units?.forEach(cu => {
      totalOnHand += parseFloat(entries[`${item.product_id}_${cu.unit_id}`]) || 0
    })

    const orderQty = Math.max(0, par.par_qty - totalOnHand)
    return { qty: orderQty, unit: par.unit_name, needsConversion: false }
  }

  // ── Save draft ─────────────────────────────────────────────────────────────
  const handleSave = async () => {
    setSaving(true)
    try {
      // Build entries — one per product per unit
      const entryList = []
      submission.sections?.forEach(section => {
        section.items?.forEach(item => {
          item.count_units?.forEach(cu => {
            const key = `${item.product_id}_${cu.unit_id}`
            const qty = entries[key]
            if (qty !== undefined && qty !== '') {
              entryList.push({
                product_id: item.product_id,
                quantity:   parseFloat(qty),
                unit_id:    cu.unit_id,
              })
            }
          })
        })
      })

      await axios.put(`/api/sheet-submissions/${submissionId}`, { entries: entryList })
      setSaved(true)
      touchedRef.current.clear()
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      console.error('Failed to save draft', e)
    } finally {
      setSaving(false)
    }
  }

  // ── Submit ─────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    if (!confirm('Submit this count sheet? This will generate purchase orders.')) return
    // Save first
    await handleSave()
    setSubmitting(true)
    try {
      const res = await axios.post(`/api/sheet-submissions/${submissionId}/submit`, {
        expected_date: expectedDate || null,
      })
      navigate(`/orders/history`)
    } catch (e) {
      console.error('Failed to submit', e)
    } finally {
      setSubmitting(false)
    }
  }

  // ── Delete draft ───────────────────────────────────────────────────────────
  const handleDeleteDraft = async () => {
    if (!confirm('Delete this draft? This cannot be undone.')) return
    try {
      await axios.delete(`/api/sheet-submissions/${submissionId}`)
      navigate(-1)
    } catch (e) {
      console.error('Failed to delete draft', e)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  if (loading)    return <div className="sheet-loading">Loading count sheet...</div>
  if (error)      return <div className="sheet-error">{error}</div>
  if (!submission) return null

  const isSubmitted = submission.status === 'submitted' && !isAdmin

  return (
    <div className="sheet-page">

      {/* ── Sticky Header ── */}
      <div className="sheet-header">
        <div className="sheet-header-left">
          <button className="sheet-back" onClick={() => navigate(-1)}>←</button>
          <div>
            <div className="sheet-title">{submission.template_name}</div>
            <div className="sheet-meta">
              {submission.location_name} · {submission.count_date}
              {isSubmitted && <span className="sheet-submitted-badge">Submitted</span>}
            </div>
            {!isSubmitted && (
              <div className="sheet-expected-date">
                <span className="sheet-expected-label">Expected:</span>
                <input
                  type="date"
                  className="sheet-date-input"
                  value={expectedDate}
                  onChange={e => setExpectedDate(e.target.value)}
                />
              </div>
            )}
          </div>
        </div>
        {!isSubmitted && (
          <div className="sheet-header-actions">
            {saved && <span className="sheet-saved">Saved ✓</span>}
            <button className="sheet-btn sheet-btn-secondary"
              onClick={handleSave} disabled={saving}>
              {saving ? 'Saving...' : 'Save Draft'}
            </button>
            <button className="sheet-btn sheet-btn-primary"
              onClick={handleSubmit} disabled={submitting || saving}>
              {submitting ? 'Submitting...' : 'Submit'}
            </button>
            <button
              className="sheet-btn sheet-btn-secondary"
              style={{ color: 'var(--error)', borderColor: 'var(--error)' }}
              onClick={handleDeleteDraft}>
              Delete
            </button>
          </div>
        )}
      </div>

      {/* Admin editing submitted sheet banner */}
      {submission.status === 'submitted' && isAdmin && (
        <div style={{
          background: 'rgba(245,158,11,0.1)',
          borderBottom: '1px solid rgba(245,158,11,0.3)',
          padding: '0.5rem 1rem',
          fontSize: '0.75rem',
          color: 'var(--warning)',
          textAlign: 'center',
        }}>
          Admin edit mode — this sheet has already been submitted
        </div>
      )}

      {/* ── Sections ── */}
        <div className="sheet-body">
          {submission.sections?.map(section => (
            <div key={section.id} className="sheet-section">
              <div className="sheet-section-title">{section.name}</div>

              {section.items?.map(item => {
                const order = getOrderQty(item)
                return (
                  <div key={item.item_id} className="sheet-item">

                    {/* NEW: Item Header containing Name, Par, and Order Summary */}
                    <div className="sheet-item-header">
                      <div className="sheet-item-name">{item.product_name}</div>

                      <div className="sheet-item-header-metrics">
                        <div className="sheet-count-par">
                          <label className="sheet-count-label">Par</label>
                          <span className="sheet-par-value">
                            {item.par
                              ? `${item.par.par_qty} ${item.par.unit_name}`
                              : '—'}
                          </span>
                        </div>

                        <div className="sheet-count-order">
                          <label className="sheet-count-label">Order</label>
                          <span className={`sheet-order-value ${order.qty > 0 ? 'sheet-order-needed' : 'sheet-order-zero'}`}>
                            {order.needsConversion
                              ? <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>calc on submit</span>
                              : order.qty !== null
                                ? `${order.qty} ${order.unit}`
                                : '—'
                            }
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Streamlined Count Rows: Only inputs and units now */}
                    {item.count_units?.map((cu) => {
                      const key = `${item.product_id}_${cu.unit_id}`
                      const qty = entries[key] ?? ''

                      return (
                        <div key={cu.unit_id} className="sheet-count-row">
                          <div className="sheet-count-unit">{cu.unit_name}</div>
                          <div className="sheet-count-input-wrap">
                            <label className="sheet-count-label">On Hand</label>
                            <NumericInput
                              className="sheet-count-input"
                              placeholder="0"
                              value={qty}
                              disabled={isSubmitted}
                              onChange={e => handleChange(item.product_id, cu.unit_id, e.target.value)}
                            />
                          </div>
                        </div>
                      )
                    })}

                  </div>
                )
              })}
            </div>
          ))}
        </div>



    </div>
  )
}
