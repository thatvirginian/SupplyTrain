// =============================================================================
// features/purchase_orders/pages/UnscheduledOrderNewPage.jsx      URL: /orders/new
// =============================================================================
// Place an order with one vendor (usually the commissary) that is not driven by
// a count: a catering, an event, a special request. No inventory is made.
// On save it becomes an ordinary purchase order (order_type 'unscheduled') and
// the page opens it, so the commissary accepts / picks / ships it as usual.
// =============================================================================
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import LineItemEditor from '../../../core/components/LineItemEditor.jsx'
import { linesToPayload } from '../../../core/utils/lineItems.js'
import { ORDER_REASONS } from '../orderConstants.js'
import '../../../core/styles/shared-ui.css'
import '../../catalog/pages/ProductDetailPage.css'   // uses .card-header / .card-title / .card-body from this stylesheet
import '../../transfers/pages/TransfersPage.css'     // shared form layout for the two "new" pages

const todayLocal = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export default function UnscheduledOrderNewPage() {
  const navigate    = useNavigate()
  const { isAdmin } = useAuth()

  const [vendors,    setVendors]    = useState([])
  const [locations,  setLocations]  = useState([])
  const [vendorId,   setVendorId]   = useState('')
  const [locationId, setLocationId] = useState('')
  const [reason,     setReason]     = useState('catering')
  const [neededBy,   setNeededBy]   = useState('')
  const [reference,  setReference]  = useState('')
  const [notes,      setNotes]      = useState('')
  const [lines,      setLines]      = useState([])
  const [saving,     setSaving]     = useState(false)
  const [error,      setError]      = useState(null)

  useEffect(() => {
    axios.get('/api/unscheduled-orders/vendors')
      .then(res => {
        setVendors(res.data)
        const comm = res.data.find(v => v.is_commissary)
        if (comm) setVendorId(String(comm.id))
      })
      .catch(() => setError('Could not load vendors.'))
    if (isAdmin) {
      axios.get('/api/locations').then(res => setLocations(res.data)).catch(() => {})
    }
  }, [isAdmin])

  const changeVendor = (next) => {
    if (lines.length && !confirm('Changing the vendor clears the items on this order. Continue?')) return
    setLines([])
    setVendorId(next)
  }

  const vendor  = vendors.find(v => String(v.id) === String(vendorId))
  const payload = linesToPayload(lines)
  const canSave = vendorId && neededBy && payload.length > 0 && (!isAdmin || locationId) && !saving

  const handleSave = async () => {
    setError(null)
    setSaving(true)
    try {
      const res = await axios.post('/api/unscheduled-orders', {
        vendor_id:     parseInt(vendorId),
        location_id:   isAdmin ? locationId : undefined,
        order_date:    todayLocal(),
        expected_date: neededBy,
        reason, reference, notes,
        items:         payload,
      })
      navigate(`/orders/${res.data.id}`)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not place the order.')
      setSaving(false)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button className="btn btn-ghost" onClick={() => navigate('/orders/history')}>← Back</button>
          <div>
            <h1 className="page-title">Unscheduled Order</h1>
            <p className="page-subtitle">Catering and other orders outside the order sheet · no inventory needed</p>
          </div>
        </div>
      </div>

      {error && <div className="alert alert-error" style={{ marginBottom: '1rem' }}>{error}</div>}

      <div className="xfer-new-grid">
        <div className="card">
          <div className="card-header"><h2 className="card-title">Order</h2></div>
          <div className="card-body xfer-form">
            {isAdmin && (
              <div className="form-group">
                <label className="form-label">Location</label>
                <select className="input" value={locationId} onChange={e => setLocationId(e.target.value)}>
                  <option value="">Choose a location…</option>
                  {locations.map(l => <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>)}
                </select>
              </div>
            )}
            <div className="form-group">
              <label className="form-label">Order from</label>
              <select className="input" value={vendorId} onChange={e => changeVendor(e.target.value)}>
                <option value="">Choose a vendor…</option>
                {vendors.map(v => (
                  <option key={v.id} value={v.id}>{v.name}{v.is_commissary ? ' (commissary)' : ''}</option>
                ))}
              </select>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Reason</label>
                <select className="input" value={reason} onChange={e => setReason(e.target.value)}>
                  {ORDER_REASONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Needed by</label>
                <input className="input" type="date" value={neededBy} min={todayLocal()}
                  onChange={e => setNeededBy(e.target.value)} />
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Reference</label>
              <input className="input" placeholder="Catering #, customer or event name"
                value={reference} maxLength={256} onChange={e => setReference(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Notes</label>
              <textarea className="input" placeholder="Anything the commissary should know"
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
            {!vendorId ? (
              <div className="line-editor-empty">Choose a vendor first.</div>
            ) : (
              <LineItemEditor
                lines={lines}
                onChange={setLines}
                searchUrl="/api/unscheduled-orders/vendor-products"
                searchParams={{ vendor_id: vendorId, location_id: isAdmin ? locationId : undefined }}
                metaFor={p => [p.vendor_code, p.packaging, p.category_name].filter(Boolean).join(' · ')}
                emptyText={`Search ${vendor?.name || 'the vendor'}'s products above to add items.`}
              />
            )}
          </div>
        </div>
      </div>

      <div className="xfer-actions">
        <button className="btn btn-ghost" onClick={() => navigate('/orders/history')}>Cancel</button>
        <button className="btn btn-primary" disabled={!canSave} onClick={handleSave}>
          {saving ? 'Placing order…' : 'Place Order'}
        </button>
      </div>
      {!canSave && !saving && (
        <p className="xfer-missing">
          Still needed: {[
            isAdmin && !locationId && 'a location',
            !vendorId && 'a vendor',
            !neededBy && 'the date it is needed',
            payload.length === 0 && 'at least one item with a quantity',
          ].filter(Boolean).join(', ')}
        </p>
      )}
    </div>
  )
}
