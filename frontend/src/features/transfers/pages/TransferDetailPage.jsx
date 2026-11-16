// =============================================================================
// features/transfers/pages/TransferDetailPage.jsx      URL: /transfers/:id
// =============================================================================
// One transfer. What the user may do comes from the API (can_edit, can_send,
// can_reopen, can_receive, can_cancel, can_delete):
//   open      either store edits the lines; the sending store marks it Sent
//   sent      the receiving store enters what arrived and confirms Received;
//             the sending store can take it back to open to fix something
//   received  read-only, shows sent vs received
// =============================================================================
import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { NumericInput } from '../../../core/components/NumericInput.jsx'
import LineItemEditor from '../../../core/components/LineItemEditor.jsx'
import { linesToPayload } from '../../../core/utils/lineItems.js'
import { formatDate, formatTimestamp } from '../../../core/utils/dateUtils.js'
import { TRANSFER_STATUS_BADGE, TRANSFER_REASONS, reasonLabel, capitalize } from '../transferConstants.js'
import '../../../core/styles/shared-ui.css'
import '../../../core/styles/order-and-print.css'
import '../../catalog/pages/ProductDetailPage.css'   // uses .card-header / .card-title / .card-body / .btn-sm from this stylesheet
import './TransfersPage.css'

const fmtQty = (n) => (n === null || n === undefined) ? '—' : String(parseFloat(n))
const who    = (email) => (email || '').split('@')[0]

export default function TransferDetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()

  const [t,       setT]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [busy,    setBusy]    = useState(false)

  // Editing (open)
  const [editing, setEditing] = useState(false)
  const [lines,   setLines]   = useState([])
  const [form,    setForm]    = useState({})

  // Receiving (sent)
  const [recv,        setRecv]        = useState({})   // item id → { qty, note }
  const [receiveNote, setReceiveNote] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await axios.get(`/api/transfers/${id}`)
      setT(res.data)
      setRecv(Object.fromEntries(res.data.items.map(i => [i.id, { qty: fmtQty(i.quantity), note: '' }])))
      setError(null)
    } catch (e) {
      setError(e.response?.status === 404 ? 'Transfer not found.' : (e.response?.data?.error || 'Could not load the transfer.'))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { load() }, [load])

  const act = async (fn, confirmText) => {
    if (confirmText && !confirm(confirmText)) return
    setBusy(true)
    setError(null)
    try {
      await fn()
      await load()
    } catch (e) {
      setError(e.response?.data?.error || 'That did not work. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const startEdit = () => {
    setLines(t.items.map(i => ({
      product_id: i.product_id, product_name: i.product_name,
      quantity: fmtQty(i.quantity), unit_id: i.unit_id, units: i.units,
    })))
    setForm({ transfer_date: String(t.transfer_date).slice(0, 10), reason: t.reason || '', notes: t.notes || '' })
    setEditing(true)
  }

  const saveEdit = () => {
    const items = linesToPayload(lines)
    if (!items.length) {
      setError('Keep at least one item with a quantity (or cancel the transfer).')
      return
    }
    return act(async () => {
      await axios.put(`/api/transfers/${id}`, { ...form, reason: form.reason || null, items })
      setEditing(false)
    })
  }

  const send    = () => act(() => axios.post(`/api/transfers/${id}/send`),
    `Mark this transfer as sent to ${t.to_location_name}? The items will be locked.`)
  const reopen  = () => act(() => axios.post(`/api/transfers/${id}/reopen`),
    'Take this transfer back to open so it can be changed?')
  const cancel  = () => act(() => axios.post(`/api/transfers/${id}/cancel`), 'Cancel this transfer?')
  const remove  = async () => {
    if (!confirm('Delete this transfer permanently?')) return
    try { await axios.delete(`/api/transfers/${id}`); navigate('/transfers') }
    catch (e) { setError(e.response?.data?.error || 'Could not delete.') }
  }
  const receive = () => act(() => axios.post(`/api/transfers/${id}/receive`, {
    received_note: receiveNote,
    items: t.items.map(i => ({
      id: i.id,
      received_quantity: recv[i.id]?.qty === '' ? 0 : recv[i.id]?.qty,
      received_note: recv[i.id]?.note || null,
    })),
  }), `Confirm these items arrived at ${t.to_location_name}?`)

  if (loading) return <div className="spinner">Loading transfer...</div>
  if (!t) return <div className="page"><div className="alert alert-error">{error}</div></div>

  const isReceived = t.status === 'received'
  const receiving  = t.can_receive

  return (
    <div className="page">
      <div className="page-header no-print">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button className="btn btn-ghost" onClick={() => navigate('/transfers')}>← Back</button>
          <div>
            <h1 className="page-title">
              <span className="xfer-route">
                {t.from_location_name}<span className="xfer-route-arrow">→</span>{t.to_location_name}
              </span>
            </h1>
            <p className="page-subtitle">Transfer #{t.id} · {formatDate(t.transfer_date)}</p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <span className={`badge ${TRANSFER_STATUS_BADGE[t.status] || 'badge-neutral'}`}>{capitalize(t.status)}</span>
          <button className="btn btn-secondary" onClick={() => window.print()}>Print</button>
          {t.can_edit && !editing && <button className="btn btn-secondary" disabled={busy} onClick={startEdit}>Edit</button>}
          {t.can_send && !editing && <button className="btn btn-primary" disabled={busy} onClick={send}>Mark Sent</button>}
          {t.can_reopen && <button className="btn btn-secondary" disabled={busy} onClick={reopen}>Reopen</button>}
          {t.can_cancel && !editing && (
            <button className="btn btn-ghost" style={{ color: 'var(--error)' }} disabled={busy} onClick={cancel}>Cancel Transfer</button>
          )}
          {t.can_delete && (
            <button className="btn btn-ghost" style={{ color: 'var(--error)' }} disabled={busy} onClick={remove}>Delete</button>
          )}
        </div>
      </div>

      {/* Print header */}
      <div className="print-only" style={{ marginBottom: '0.75rem' }}>
        <h2>Transfer #{t.id}: {t.from_location_name} → {t.to_location_name}</h2>
        <p>{formatDate(t.transfer_date)} · {capitalize(t.status)}</p>
      </div>

      {error && <div className="alert alert-error" style={{ marginBottom: '1rem' }}>{error}</div>}

      {/* Meta */}
      <div className="card" style={{ marginBottom: '1rem', padding: '0.6rem 1rem' }}>
        {editing ? (
          <div className="form-row" style={{ gridTemplateColumns: '160px 180px 1fr' }}>
            <div className="form-group">
              <label className="form-label">Date</label>
              <input className="input" type="date" value={form.transfer_date}
                onChange={e => setForm(f => ({ ...f, transfer_date: e.target.value }))} />
            </div>
            <div className="form-group">
              <label className="form-label">Reason</label>
              <select className="input" value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}>
                <option value="">—</option>
                {TRANSFER_REASONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Notes</label>
              <input className="input" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
            </div>
          </div>
        ) : (
          <div className="xfer-meta">
            {t.reason && <span><span className="xfer-meta-label">Reason</span>{reasonLabel(t.reason)}</span>}
            <span><span className="xfer-meta-label">Created</span>{formatTimestamp(t.created_at)} · {who(t.created_by)}</span>
            {t.sent_at && <span><span className="xfer-meta-label">Sent</span>{formatTimestamp(t.sent_at)} · {who(t.sent_by)}</span>}
            {t.received_at && <span><span className="xfer-meta-label">Received</span>{formatTimestamp(t.received_at)} · {who(t.received_by)}</span>}
            {t.cancelled_at && <span><span className="xfer-meta-label">Cancelled</span>{formatTimestamp(t.cancelled_at)} · {who(t.cancelled_by)}</span>}
            {t.notes && <span><span className="xfer-meta-label">Notes</span>{t.notes}</span>}
            {t.received_note && <span><span className="xfer-meta-label">Receiving note</span>{t.received_note}</span>}
          </div>
        )}
      </div>

      {/* Lines */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">{editing ? lines.length : t.items.length} items</h2>
          {receiving && (
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
              Change a quantity only if less (or more) arrived than was sent
            </span>
          )}
        </div>

        {editing ? (
          <div className="card-body">
            <LineItemEditor lines={lines} onChange={setLines} searchUrl="/api/transfers/products"
              metaFor={p => p.category_name || ''} />
            <div className="xfer-actions">
              <button className="btn btn-ghost" disabled={busy} onClick={() => setEditing(false)}>Discard changes</button>
              <button className="btn btn-primary" disabled={busy} onClick={saveEdit}>
                {busy ? 'Saving…' : 'Save Changes'}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="xfer-lines-row xfer-lines-header">
              <span>Product</span>
              <span style={{ textAlign: 'right' }}>Sent</span>
              <span>Unit</span>
              <span style={{ textAlign: 'right' }}>{receiving || isReceived ? 'Received' : ''}</span>
              <span>{receiving || isReceived ? 'Note' : ''}</span>
            </div>
            {t.items.map(i => {
              const diff = isReceived && i.received_quantity !== null
                && parseFloat(i.received_quantity) !== parseFloat(i.quantity)
              return (
                <div key={i.id} className="xfer-lines-row">
                  <span>
                    {i.product_name}
                    {i.base_unit && i.base_unit_id !== i.unit_id && (
                      <span className="xfer-base">= {fmtQty(i.base_quantity)} {i.base_unit}</span>
                    )}
                  </span>
                  <span className="xfer-num">{fmtQty(i.quantity)}</span>
                  <span>{i.unit}</span>
                  {receiving ? (
                    <>
                      <NumericInput className="input xfer-num" style={{ padding: '0.3rem 0.4rem' }}
                        value={recv[i.id]?.qty ?? ''}
                        onChange={e => setRecv(r => ({ ...r, [i.id]: { ...r[i.id], qty: e.target.value } }))} />
                      <input className="input" style={{ padding: '0.3rem 0.4rem', fontSize: '0.75rem' }}
                        placeholder="Damaged, short…" value={recv[i.id]?.note ?? ''}
                        onChange={e => setRecv(r => ({ ...r, [i.id]: { ...r[i.id], note: e.target.value } }))} />
                    </>
                  ) : (
                    <>
                      <span className={`xfer-num ${diff ? 'xfer-diff' : ''}`}>
                        {isReceived ? fmtQty(i.received_quantity) : ''}
                        {isReceived && i.received_base_unit && i.received_base_unit_id !== i.unit_id && (
                          <span className="xfer-base">= {fmtQty(i.received_base_quantity)} {i.received_base_unit}</span>
                        )}
                      </span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        {isReceived ? (i.received_note || '') : ''}
                      </span>
                    </>
                  )}
                </div>
              )
            })}
          </>
        )}

        {receiving && (
          <div className="xfer-receive-bar no-print">
            <input className="input" placeholder="Receiving note (optional)"
              value={receiveNote} onChange={e => setReceiveNote(e.target.value)} />
            <button className="btn btn-primary" disabled={busy} onClick={receive}>
              {busy ? 'Saving…' : 'Confirm Received'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
