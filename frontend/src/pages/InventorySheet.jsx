import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../App.jsx'
import './count-sheet.css'

export default function InventorySheet() {
  const { submissionId } = useParams()
  const navigate         = useNavigate()
  const { isAdmin, isManager } = useAuth()

  const [submission,  setSubmission]  = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)
  const [saving,      setSaving]      = useState(false)
  const [submitting,  setSubmitting]  = useState(false)
  const [saved,       setSaved]       = useState(false)

  // entries: { `${product_id}_${unit_id}`: quantity }
  const [entries,   setEntries]   = useState({})
  const [collapsedSections, setCollapsedSections] = useState(new Set())

  const fetchSubmission = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.get(`/api/inventory-submissions/${submissionId}`)
      setSubmission(res.data)

      // Pre-populate from existing counts
      const saved = {}
      res.data.items?.forEach(item => {
        if (item.entered_quantity != null && item.entered_unit_id != null) {
          saved[`${item.product_id}_${item.entered_unit_id}`] = String(item.entered_quantity)
        } else if (item.base_quantity != null) {
          saved[`${item.product_id}_${item.base_unit_id}`] = String(item.base_quantity)
        }
      })
      setEntries(saved)
    } catch (e) {
      setError('Failed to load inventory.')
    } finally {
      setLoading(false)
    }
  }, [submissionId])

  useEffect(() => { fetchSubmission() }, [fetchSubmission])

  const handleChange = (productId, unitId, value) => {
    setEntries(e => ({ ...e, [`${productId}_${unitId}`]: value }))
  }

  const buildEntryList = () => {
    if (!submission?.template_sections) return []
    const entryList = []
    submission.template_sections?.forEach(section => {
      section.items?.forEach(item => {
        const countUnits = item.count_units?.length > 0
          ? item.count_units
          : [{ unit_id: item.base_unit_id, unit_name: item.base_unit }]

        countUnits.forEach(cu => {
          const key = `${item.product_id}_${cu.unit_id}`
          const qty = entries[key]
          if (qty !== undefined && qty !== '') {
            entryList.push({
              product_id:   item.product_id,
              quantity:     parseFloat(qty),
              unit_id:      cu.unit_id,
              base_unit_id: item.base_unit_id,
            })
          }
        })
      })
    })
    return entryList
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      // Convert entries to base units server-side via the save endpoint
      const entryList = buildEntryList()
      await axios.put(`/api/inventory-submissions/${submissionId}/save`, {
        entries: entryList
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      console.error('Failed to save', e)
    } finally {
      setSaving(false)
    }
  }

  const handleSubmit = async () => {
    if (!confirm('Submit this inventory? You will still be able to view it after.')) return
    await handleSave()
    setSubmitting(true)
    try {
      await axios.post(`/api/inventory-submissions/${submissionId}/submit`)
      navigate('/inventory/history')
    } catch (e) {
      console.error('Failed to submit', e)
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm('Delete this draft inventory?')) return
    try {
      await axios.delete(`/api/inventory-submissions/${submissionId}`)
      navigate('/inventory/history')
    } catch (e) { console.error(e) }
  }

  const toggleSection = (sectionId) => {
    setCollapsedSections(prev => {
      const next = new Set(prev)
      next.has(sectionId) ? next.delete(sectionId) : next.add(sectionId)
      return next
    })
  }

  if (loading)     return <div className="sheet-loading">Loading inventory...</div>
  if (error)       return <div className="sheet-error">{error}</div>
  if (!submission) return null

  const isSubmitted = submission.status === 'submitted' && !isAdmin

  // Use template sections if available, otherwise group items by category
  const sections = submission.template_sections || []

  return (
    <div className="sheet-page">
      {/* Header */}
      <div className="sheet-header">
        <div className="sheet-header-left">
          <button className="sheet-back" onClick={() => navigate(-1)}>←</button>
          <div>
            <div className="sheet-title">{submission.template_name || 'Manual Inventory'}</div>
            <div className="sheet-meta">
              {submission.location_name} · {submission.count_date}
              {isSubmitted && <span className="sheet-submitted-badge">Submitted</span>}
            </div>
          </div>
        </div>
        {!isSubmitted && (
          <div className="sheet-header-actions">
            {saved && <span className="sheet-saved">Saved ✓</span>}
            <button className="sheet-btn sheet-btn-secondary"
              onClick={handleSave} disabled={saving}>
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button className="sheet-btn sheet-btn-primary"
              onClick={handleSubmit} disabled={submitting || saving}>
              {submitting ? 'Submitting...' : 'Submit'}
            </button>
            {isManager && (
              <button className="sheet-btn sheet-btn-secondary"
                style={{ color: 'var(--error)', borderColor: 'var(--error)' }}
                onClick={handleDelete}>Delete</button>
            )}
          </div>
        )}
      </div>

      {submission.status === 'submitted' && isAdmin && (
        <div style={{
          background: 'rgba(245,158,11,0.1)',
          borderBottom: '1px solid rgba(245,158,11,0.3)',
          padding: '0.5rem 1rem',
          fontSize: '0.75rem',
          color: 'var(--warning)',
          textAlign: 'center',
        }}>
          Admin view — this inventory has been submitted
        </div>
      )}

      {/* Body */}
      <div className="sheet-body">
        <div className="sheet-sections-grid">
          {sections.map(section => {
            const isCollapsed = collapsedSections.has(section.id)
            const filledCount = section.items?.filter(item => {
              const units = item.count_units?.length > 0
                ? item.count_units
                : [{ unit_id: item.base_unit_id }]
              return units.some(cu => {
                const v = entries[`${item.product_id}_${cu.unit_id}`]
                return v !== undefined && v !== ''
              })
            }).length || 0
            const totalCount = section.items?.length || 0

            return (
              <div key={section.id} className="sheet-section">
                <div className="sheet-section-title"
                  style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                  onClick={() => toggleSection(section.id)}>
                  <span>{section.name}</span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ fontSize: '0.65rem', opacity: 0.7, fontWeight: 400 }}>
                      {filledCount}/{totalCount}
                    </span>
                    <span style={{ fontSize: '0.65rem' }}>{isCollapsed ? '▶' : '▼'}</span>
                  </span>
                </div>

                {!isCollapsed && section.items?.map(item => {
                  const countUnits = item.count_units?.length > 0
                    ? item.count_units
                    : [{ unit_id: item.base_unit_id, unit_name: item.base_unit }]

                  return (
                    <div key={item.id} className="sheet-item">
                      <div className="sheet-item-header">
                        <div className="sheet-item-name">{item.product_name}</div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                          {item.base_unit}
                        </div>
                      </div>
                      {countUnits.map(cu => {
                        const key = `${item.product_id}_${cu.unit_id}`
                        const qty = entries[key] ?? ''
                        return (
                          <div key={cu.unit_id} className="sheet-count-row">
                            <div className="sheet-count-unit">{cu.unit_name}</div>
                            <div className="sheet-count-input-wrap">
                              <label className="sheet-count-label">Quantity</label>
                              <input
                                className="sheet-count-input"
                                type="number"
                                min="0"
                                step="any"
                                inputMode="decimal"
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
            )
          })}
        </div>
      </div>

      {/* Footer */}
      {!isSubmitted && (
        <div className="sheet-footer">
          <button className="sheet-btn sheet-btn-secondary sheet-btn-full"
            onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Draft'}
          </button>
          <button className="sheet-btn sheet-btn-primary sheet-btn-full"
            onClick={handleSubmit} disabled={submitting || saving}>
            {submitting ? 'Submitting...' : 'Submit'}
          </button>
        </div>
      )}
    </div>
  )
}
