import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { NumericInput } from '../../../core/components/NumericInput.jsx'
import { formatDate, formatTimestamp } from '../../../core/utils/dateUtils.js'
import '../../../core/styles/shared-ui.css'   // .alert
import '../../../core/styles/count-entry-sheet.css'
import './ProductionPages.css'

// One production run: what the commissary made (Made) and what is on hand after
// production (End Inv), product by product, in the unit set on the production
// template. Several runs a day add up. The End Inv boxes are the commissary's
// inventory for the day: submitting the run submits that inventory too.
// Drafts: Save / Submit / Delete. Submitted: read-only, except for admins and
// commissary GMs (can_edit), whose saves are recorded as corrections.

function fmtQty(v) {
  if (v == null) return ''
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 })
}

export default function ProductionRunPage() {
  const { runId } = useParams()
  const navigate  = useNavigate()

  const [run,        setRun]        = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [entries,    setEntries]    = useState({})     // Made:    { product_id: '2.5' }
  const [endEntries, setEndEntries] = useState({})     // End Inv: { product_id: '12' }
  const [dirty,      setDirty]      = useState(false)
  const [notes,      setNotes]      = useState('')     // correction reason
  const [saving,     setSaving]     = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [saved,      setSaved]      = useState(false)
  const [saveError,  setSaveError]  = useState(null)   // { message, missing: [] }
  const [collapsed,  setCollapsed]  = useState(new Set())

  const fetchRun = useCallback(async () => {
    setError(null)
    try {
      const res = await axios.get(`/api/production-runs/${runId}`)
      setRun(res.data)
      const e = {}, end = {}
      res.data.lines.forEach(l => { e[l.product_id] = String(l.quantity) })
      res.data.sections.forEach(s => s.items.forEach(it => {
        if (it.end_quantity != null) end[it.product_id] = String(it.end_quantity)
      }))
      setEntries(e)
      setEndEntries(end)
      setDirty(false)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not load the production run.')
    } finally {
      setLoading(false)
    }
  }, [runId])

  useEffect(() => { fetchRun() }, [fetchRun])

  const allItems = run ? run.sections.flatMap(s => s.items) : []

  const handleChange = (productId, value) => {
    setEntries(prev => ({ ...prev, [productId]: value }))
    setDirty(true)
  }

  const handleEndChange = (productId, value) => {
    setEndEntries(prev => ({ ...prev, [productId]: value }))
    setDirty(true)
  }

  // Returns true when the save worked, so Submit stops on a failed save.
  const handleSave = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      await axios.put(`/api/production-runs/${runId}/save`, {
        // One entry per product row; blank Made = no amount (removes a draft line),
        // blank End Inv = not counted.
        entries: allItems.map(it => {
          const v = entries[it.product_id]
          const ev = endEntries[it.product_id]
          return {
            product_id:   it.product_id,
            quantity:     v === undefined || v === '' ? null : v,
            end_quantity: ev === undefined || ev === '' ? null : ev,
          }
        }),
        correction_notes: notes.trim() || null,
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
      await fetchRun()
      return true
    } catch (e) {
      setSaveError({
        message: e.response?.data?.error || 'Save failed. Check your connection and try again.',
        missing: e.response?.data?.missing_conversions || [],
      })
      return false
    } finally {
      setSaving(false)
    }
  }

  const handleSubmit = async () => {
    if (!confirm('Submit this production run? What was made counts toward the day\'s production, and the End Inv becomes the commissary\'s inventory.')) return
    if (!(await handleSave())) return
    setSubmitting(true)
    try {
      await axios.post(`/api/production-runs/${runId}/submit`)
      navigate('/production')
    } catch (e) {
      setSaveError({ message: e.response?.data?.error || 'Submit failed.', missing: [] })
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async () => {
    const what = run.status === 'submitted'
      ? 'Delete this SUBMITTED production run? Its amounts will no longer count toward the day, and its End Inv inventory is deleted too.'
      : 'Delete this draft production run?'
    if (!confirm(what)) return
    try {
      await axios.delete(`/api/production-runs/${runId}`)
      navigate('/production')
    } catch (e) {
      setSaveError({ message: e.response?.data?.error || 'Delete failed.', missing: [] })
    }
  }

  const toggleSection = (id) => setCollapsed(prev => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  if (loading) return <div className="sheet-loading">Loading production run...</div>
  if (error)   return <div className="sheet-error">{error}</div>
  if (!run)    return null

  const isSubmitted  = run.status === 'submitted'
  const readOnly     = !run.can_edit
  const isCorrecting = isSubmitted && run.can_edit

  const actions = (full) => (
    <>
      <button className={`sheet-btn sheet-btn-secondary ${full ? 'sheet-btn-full' : ''}`}
        onClick={handleSave} disabled={saving || (isCorrecting && !dirty)}>
        {saving ? 'Saving...' : isCorrecting ? 'Save Corrections' : full ? 'Save Draft' : 'Save'}
      </button>
      {!isSubmitted && (
        <button className={`sheet-btn sheet-btn-primary ${full ? 'sheet-btn-full' : ''}`}
          onClick={handleSubmit} disabled={submitting || saving}>
          {submitting ? 'Submitting...' : 'Submit'}
        </button>
      )}
    </>
  )

  return (
    <div className="sheet-page">
      <div className="sheet-header">
        <div className="sheet-header-left">
          <button className="sheet-back" onClick={() => navigate('/production')}>←</button>
          <div>
            <div className="sheet-title">{run.template_name || 'Production Run'}</div>
            <div className="sheet-meta">
              {run.location_name} · {formatDate(run.production_date)}
              {isSubmitted && <span className="sheet-submitted-badge">Submitted</span>}
            </div>
          </div>
        </div>
        <div className="sheet-header-actions">
          {saved && <span className="sheet-saved">Saved ✓</span>}
          {!readOnly && actions(false)}
          {run.can_delete && (
            <button className="sheet-btn sheet-btn-secondary"
              style={{ color: 'var(--error)', borderColor: 'var(--error)' }}
              onClick={handleDelete}>Delete</button>
          )}
        </div>
      </div>

      {isSubmitted && (
        <div className="prod-banner">
          Submitted by {run.submitted_by} · {formatTimestamp(run.submitted_at)}
          {isCorrecting && ' — changes you save are recorded as corrections; the submitted values are kept.'}
        </div>
      )}

      {isCorrecting && (
        <div className="prod-notes">
          <label className="form-label" style={{ margin: 0 }}>Reason</label>
          <input className="input" placeholder="Why are these amounts changing? (optional)"
            value={notes} onChange={e => setNotes(e.target.value)} />
        </div>
      )}

      <div className="prod-end-note">
        End Inv = what is on hand after production. It becomes {run.location_name}'s inventory
        for {formatDate(run.production_date)}{isSubmitted ? '' : ' when you submit'}; leave it blank for products not counted.
        {run.inventory_submission_id && (
          <> {' '}<a href={`/inventory/${run.inventory_submission_id}`}
            onClick={e => { e.preventDefault(); navigate(`/inventory/${run.inventory_submission_id}`) }}>
            View inventory →</a></>
        )}
      </div>

      {saveError && (
        <div className="alert alert-error" style={{ margin: '0.75rem 1rem 0' }}>
          <div>{saveError.message}</div>
          {saveError.missing.length > 0 && (
            <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.2rem' }}>
              {saveError.missing.map(m => (
                <li key={`${m.product_id}_${m.unit_id}`}>
                  {m.product_name}: {m.unit_name} has no conversion to {m.base_unit}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="sheet-body">
        {run.sections.length === 0 && (
          <div className="alert alert-warning">This production template has no products yet.</div>
        )}
        <div className="sheet-sections-grid">
          {run.sections.map(section => {
            const isCollapsed = collapsed.has(section.id)
            const filled = section.items.filter(it =>
              (entries[it.product_id] ?? '') !== '' || (endEntries[it.product_id] ?? '') !== '').length
            return (
              <div key={section.id} className="sheet-section">
                <div className="sheet-section-title"
                  style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                  onClick={() => toggleSection(section.id)}>
                  <span>{section.name}</span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ fontSize: '0.65rem', opacity: 0.7, fontWeight: 400 }}>
                      {filled}/{section.items.length}
                    </span>
                    <span style={{ fontSize: '0.65rem' }}>{isCollapsed ? '▶' : '▼'}</span>
                  </span>
                </div>

                {!isCollapsed && section.items.map(it => {
                  const line = it.line
                  const corrected = line && line.corrected_at
                  const et = it.earlier_today
                  return (
                    <div key={it.product_id} className="sheet-item">
                      <div className="sheet-item-header">
                        <div>
                          <div className="sheet-item-name">
                            {it.product_name}{it.not_on_template && ' *'}
                          </div>
                          {et && (
                            <div className="prod-earlier">
                              Earlier today: {et.quantity != null
                                ? `${fmtQty(et.quantity)} ${et.unit_name}`
                                : et.base.map(b => `${fmtQty(b.quantity)} ${b.unit_name}`).join(' + ')}
                              {' '}({et.runs} {et.runs === 1 ? 'run' : 'runs'})
                            </div>
                          )}
                        </div>
                        {line && line.unit_id !== line.base_unit_id && (
                          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                            = {fmtQty(line.base_quantity)} {line.base_unit}
                          </div>
                        )}
                      </div>
                      <div className="sheet-count-row prod-count-row">
                        <div className="sheet-count-unit"
                          title={it.not_on_template ? 'No longer on the template' : undefined}>
                          {it.unit_name}
                        </div>
                        <div className="sheet-count-input-wrap">
                          <label className="sheet-count-label">Made</label>
                          <NumericInput
                            className="sheet-count-input"
                            placeholder="0"
                            value={entries[it.product_id] ?? ''}
                            disabled={readOnly}
                            onChange={e => handleChange(it.product_id, e.target.value)}
                          />
                        </div>
                        <div className="sheet-count-input-wrap">
                          <label className="sheet-count-label">End Inv</label>
                          <NumericInput
                            className="sheet-count-input"
                            placeholder="—"
                            value={endEntries[it.product_id] ?? ''}
                            disabled={readOnly}
                            onChange={e => handleEndChange(it.product_id, e.target.value)}
                          />
                        </div>
                      </div>
                      {it.end_other?.length > 0 && (
                        <div className="prod-end-other">
                          Also counted: {it.end_other.map(o => `${fmtQty(o.quantity)} ${o.unit_name}`).join(' + ')}
                        </div>
                      )}
                      {corrected && (
                        <div className="prod-was" title={`${line.corrected_by} · ${formatTimestamp(line.corrected_at)}${line.correction_notes ? ' · ' + line.correction_notes : ''}`}>
                          was {fmtQty(line.original_quantity)} {it.unit_name} · corrected by {line.corrected_by}
                          {line.correction_notes && ` · ${line.correction_notes}`}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>

      {!readOnly && <div className="sheet-footer">{actions(true)}</div>}
    </div>
  )
}
