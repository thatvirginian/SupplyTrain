// =============================================================================
// features/transfers/pages/TransferNewPage.jsx      URL: /transfers/new
// =============================================================================
// Write up a store-to-store transfer. A store user picks whether their store is
// sending or receiving, and the other store. Admins pick both stores.
// Saved as 'open'; the sending store marks it sent on the detail page.
// =============================================================================
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import LineItemEditor from '../../../core/components/LineItemEditor.jsx'
import { linesToPayload } from '../../../core/utils/lineItems.js'
import { TRANSFER_REASONS } from '../transferConstants.js'
import '../../../core/styles/shared-ui.css'
import '../../catalog/pages/ProductDetailPage.css'   // uses .card-header / .card-title / .card-body from this stylesheet
import './TransfersPage.css'

const todayLocal = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export default function TransferNewPage() {
  const navigate    = useNavigate()
  const { isAdmin } = useAuth()

  const [locations, setLocations] = useState([])
  const [myLoc,     setMyLoc]     = useState(null)
  const [loaded,    setLoaded]    = useState(false)

  // Store users: their store + direction + the other store
  const [sending,   setSending]   = useState(true)
  const [otherLoc,  setOtherLoc]  = useState('')
  // Admins: both stores
  const [fromLoc,   setFromLoc]   = useState('')
  const [toLoc,     setToLoc]     = useState('')

  const [date,      setDate]      = useState(todayLocal())
  const [reason,    setReason]    = useState('shortage')
  const [notes,     setNotes]     = useState('')
  const [lines,     setLines]     = useState([])
  const [saving,    setSaving]    = useState(false)
  const [error,     setError]     = useState(null)

  useEffect(() => {
    Promise.all([
      axios.get('/api/locations'),
      axios.get('/api/transfers', { params: { per_page: 1 } }),   // carries my_location_id
    ]).then(([locRes, meRes]) => {
      setLocations(locRes.data)
      setMyLoc(meRes.data.my_location_id)
    }).catch(() => setError('Could not load stores.'))
      .finally(() => setLoaded(true))
  }, [])

  const from = isAdmin ? fromLoc : (sending ? myLoc : otherLoc)
  const to   = isAdmin ? toLoc   : (sending ? otherLoc : myLoc)
  const myName = locations.find(l => l.store_guid === myLoc)?.location_name

  const payload = linesToPayload(lines)
  const canSave = from && to && from !== to && payload.length > 0 && !saving

  const handleSave = async () => {
    setError(null)
    setSaving(true)
    try {
      const res = await axios.post('/api/transfers', {
        from_location_id: from,
        to_location_id:   to,
        transfer_date:    date,
        reason, notes,
        items:            payload,
      })
      navigate(`/transfers/${res.data.id}`)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not save the transfer.')
      setSaving(false)
    }
  }

  if (!loaded) return <div className="spinner">Loading...</div>

  if (!isAdmin && !myLoc) {
    return (
      <div className="page">
        <div className="alert alert-error">
          Your account is not linked to a store, so you cannot write up a transfer. Ask an admin.
        </div>
      </div>
    )
  }

  const storeOptions = (exclude) => locations
    .filter(l => l.store_guid !== exclude)
    .map(l => <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>)

  return (
    <div className="page">
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button className="btn btn-ghost" onClick={() => navigate('/transfers')}>← Back</button>
          <div>
            <h1 className="page-title">New Transfer</h1>
            <p className="page-subtitle">Product moving from one store to another</p>
          </div>
        </div>
      </div>

      {error && <div className="alert alert-error" style={{ marginBottom: '1rem' }}>{error}</div>}

      <div className="xfer-new-grid">
        <div className="card">
          <div className="card-header"><h2 className="card-title">Transfer</h2></div>
          <div className="card-body xfer-form">
            {isAdmin ? (
              <>
                <div className="form-group">
                  <label className="form-label">From (sending)</label>
                  <select className="input" value={fromLoc} onChange={e => setFromLoc(e.target.value)}>
                    <option value="">Choose a store…</option>
                    {storeOptions(toLoc)}
                  </select>
                </div>
                <button type="button" className="btn btn-ghost btn-sm xfer-swap" title="Swap"
                  onClick={() => { setFromLoc(toLoc); setToLoc(fromLoc) }}>⇅</button>
                <div className="form-group">
                  <label className="form-label">To (receiving)</label>
                  <select className="input" value={toLoc} onChange={e => setToLoc(e.target.value)}>
                    <option value="">Choose a store…</option>
                    {storeOptions(fromLoc)}
                  </select>
                </div>
              </>
            ) : (
              <>
                <div className="form-group">
                  <label className="form-label">{myName || 'Your store'} is</label>
                  <div className="xfer-direction">
                    <button type="button" className={sending ? 'is-active' : ''} onClick={() => setSending(true)}>
                      Sending
                    </button>
                    <button type="button" className={!sending ? 'is-active' : ''} onClick={() => setSending(false)}>
                      Receiving
                    </button>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">{sending ? 'Sending to' : 'Receiving from'}</label>
                  <select className="input" value={otherLoc} onChange={e => setOtherLoc(e.target.value)}>
                    <option value="">Choose a store…</option>
                    {storeOptions(myLoc)}
                  </select>
                </div>
              </>
            )}

            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Date</label>
                <input className="input" type="date" value={date} onChange={e => setDate(e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Reason</label>
                <select className="input" value={reason} onChange={e => setReason(e.target.value)}>
                  {TRANSFER_REASONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Notes</label>
              <textarea className="input" placeholder="Who is driving it over, anything to know"
                value={notes} onChange={e => setNotes(e.target.value)} />
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Items</h2>
            <span className="xfer-count">{payload.length} with a quantity</span>
          </div>
          <div className="card-body">
            <LineItemEditor
              lines={lines}
              onChange={setLines}
              searchUrl="/api/transfers/products"
              metaFor={p => [p.category_name, p.base_unit && `base: ${p.base_unit}`].filter(Boolean).join(' · ')}
            />
          </div>
        </div>
      </div>

      <div className="xfer-actions">
        <button className="btn btn-ghost" onClick={() => navigate('/transfers')}>Cancel</button>
        <button className="btn btn-primary" disabled={!canSave} onClick={handleSave}>
          {saving ? 'Saving…' : 'Save Transfer'}
        </button>
      </div>
      {!canSave && !saving && (
        <p className="xfer-missing">
          Still needed: {[
            !(from && to) && 'both stores',
            payload.length === 0 && 'at least one item with a quantity',
          ].filter(Boolean).join(', ')}
        </p>
      )}
    </div>
  )
}
