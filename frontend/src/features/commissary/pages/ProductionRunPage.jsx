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
// Submitting and corrections are signed by whoever is signed in on the device
// (the sign-in box opens by itself when nobody is).

// QC: average + result of the weights typed so far, against target ± tolerance.
function qcLive(weights, target, tolerance) {
  const nums = weights.map(w => parseFloat(w)).filter(w => !isNaN(w) && w > 0)
  if (nums.length === 0) return null
  const avg = nums.reduce((a, b) => a + b, 0) / nums.length
  const spread = nums.length > 1 ? Math.max(...nums) - Math.min(...nums) : 0
  let result = 'none'
  if (target != null) {
    const tol = tolerance || 0
    result = avg < target - tol - 1e-9 ? 'low' : avg > target + tol + 1e-9 ? 'high' : 'ok'
  }
  return { avg, spread, result, n: nums.length }
}

const QC_BADGE = { ok: 'badge-success', low: 'badge-warning', high: 'badge-error', none: 'badge-neutral' }
const QC_LABEL = { ok: 'on target', low: 'light', high: 'heavy', none: 'no target' }

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
  const [qcEntries,  setQcEntries]  = useState({})     // QC:      { product_id: ['4.4', '', '', ''] }
  const [madeBy,     setMadeBy]     = useState({})     // Made by: { product_id: 'Yazmin' } (typed)
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
      const e = {}, end = {}, qc = {}, mb = {}
      const n = res.data.qc_samples || 4
      res.data.lines.forEach(l => { e[l.product_id] = String(l.quantity) })
      res.data.sections.forEach(s => s.items.forEach(it => {
        if (it.end_quantity != null) end[it.product_id] = String(it.end_quantity)
        if (it.made_by) mb[it.product_id] = it.made_by
        if (it.qc_spec || it.qc_check) {
          const w = (it.qc_check?.weights || []).map(String)
          qc[it.product_id] = [...w, ...Array(Math.max(0, n - w.length)).fill('')]
        }
      }))
      setEntries(e)
      setEndEntries(end)
      setQcEntries(qc)
      setMadeBy(mb)
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

  const handleMadeByChange = (productId, value) => {
    setMadeBy(prev => ({ ...prev, [productId]: value }))
    setDirty(true)
  }

  const handleQcChange = (productId, idx, value) => {
    setQcEntries(prev => {
      const w = [...(prev[productId] || [])]
      w[idx] = value
      return { ...prev, [productId]: w }
    })
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
          const row = {
            product_id:   it.product_id,
            quantity:     v === undefined || v === '' ? null : v,
            end_quantity: ev === undefined || ev === '' ? null : ev,
            made_by:      (madeBy[it.product_id] || '').trim() || null,
          }
          // QC weights only for products weighed for QC (or already weighed on this run)
          if (qcEntries[it.product_id]) {
            row.qc_weights = qcEntries[it.product_id].map(w => (w === '' ? null : w))
          }
          return row
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
          Submitted by {run.submitted_by_name || run.submitted_by} · {formatTimestamp(run.submitted_at)}
          {isCorrecting && ' — changes you save are recorded as corrections; the submitted values are kept.'}
        </div>
      )}

      {(run.signoffs || []).some(s => s.action === 'production_run.correct') && (
        <div className="prod-signoffs">
          {run.signoffs.filter(s => s.action === 'production_run.correct').map((s, i) => (
            <div key={i}>Corrected by {s.signer_name} · {formatTimestamp(s.signed_at)}{s.note ? ` · ${s.note}` : ''}</div>
          ))}
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
        {/* Names typed on earlier runs at this commissary, offered while typing "Made by" */}
        <datalist id="made-by-names">
          {(run.made_by_suggestions || []).map(n => <option key={n} value={n} />)}
        </datalist>
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

                {!isCollapsed && (
                  // Column headings for the one-line-per-product layout (wide screens only)
                  <div className="prod-col-head" aria-hidden="true">
                    <span>Product</span><span>Unit</span><span>Made</span><span>End Inv</span><span>Made by</span>
                  </div>
                )}

                {!isCollapsed && section.items.map(it => {
                  const line = it.line
                  const corrected = line && line.corrected_at
                  const et = it.earlier_today
                  return (
                    <div key={it.product_id} className="prod-row">
                      <div className="prod-row-name">
                        <div className="prod-row-title">
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
                        {line && line.unit_id !== line.base_unit_id && (
                          <div className="prod-earlier">made = {fmtQty(line.base_quantity)} {line.base_unit}</div>
                        )}
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

                      <div className="prod-row-unit"
                        title={it.not_on_template ? 'No longer on the template' : undefined}>
                        {it.unit_name}
                      </div>

                      <div className="prod-row-made">
                        <label className="sheet-count-label prod-mobile-label">Made</label>
                        <NumericInput
                          className="sheet-count-input prod-row-input"
                          aria-label={`${it.product_name} made (${it.unit_name})`}
                          value={entries[it.product_id] ?? ''}
                          disabled={readOnly}
                          onChange={e => handleChange(it.product_id, e.target.value)}
                        />
                      </div>

                      <div className="prod-row-end">
                        <label className="sheet-count-label prod-mobile-label">End Inv</label>
                        <NumericInput
                          className="sheet-count-input prod-row-input"
                          aria-label={`${it.product_name} end inventory (${it.unit_name})`}
                          value={endEntries[it.product_id] ?? ''}
                          disabled={readOnly}
                          onChange={e => handleEndChange(it.product_id, e.target.value)}
                        />
                      </div>

                      <div className="prod-row-by">
                        <label className="sheet-count-label prod-mobile-label" htmlFor={`mb-${it.product_id}`}>Made by</label>
                        <input id={`mb-${it.product_id}`}
                          className="input prod-made-by-input"
                          aria-label={`${it.product_name} made by`}
                          list="made-by-names"
                          placeholder="Name"
                          maxLength={80}
                          autoComplete="off"
                          value={madeBy[it.product_id] ?? ''}
                          disabled={readOnly}
                          onChange={e => handleMadeByChange(it.product_id, e.target.value)}
                        />
                      </div>

                      {qcEntries[it.product_id] && (() => {
                        const spec = it.qc_spec
                        const chk  = it.qc_check
                        // A run's weights are judged against the target they were first saved with
                        const target = chk ? chk.target_weight : spec?.target_weight
                        const tol    = chk ? chk.tolerance     : spec?.tolerance
                        const scale  = chk ? chk.scale_unit    : spec?.scale_unit
                        const pkg    = chk ? chk.package_unit  : spec?.package_unit
                        const live   = qcLive(qcEntries[it.product_id], target, tol)
                        return (
                          <div className="prod-qc">
                            <div className="prod-qc-label">
                              QC · {pkg} weights ({scale})
                              {target != null && (
                                <span className="prod-qc-target">target {fmtQty(target)} ± {fmtQty(tol)}</span>
                              )}
                            </div>
                            <div className="prod-qc-boxes">
                              {qcEntries[it.product_id].map((w, i) => (
                                <NumericInput key={i}
                                  className="sheet-count-input prod-qc-input"
                                  aria-label={`${it.product_name} QC weight ${i + 1}`}
                                  placeholder={`#${i + 1}`}
                                  value={w}
                                  disabled={readOnly}
                                  onChange={e => handleQcChange(it.product_id, i, e.target.value)}
                                />
                              ))}
                            </div>
                            <div className="prod-qc-result">
                              {live ? (
                                <>
                                  avg <strong>{fmtQty(Math.round(live.avg * 1000) / 1000)}</strong>
                                  {live.n > 1 && <> · spread {fmtQty(Math.round(live.spread * 1000) / 1000)}</>}
                                  {' '}<span className={`badge ${QC_BADGE[live.result]}`}>{QC_LABEL[live.result]}</span>
                                </>
                              ) : <span className="prod-muted">not weighed</span>}
                            </div>
                          </div>
                        )
                      })()}
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
