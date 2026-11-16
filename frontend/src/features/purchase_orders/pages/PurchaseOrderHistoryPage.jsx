import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatDateShort } from '../../../core/utils/dateUtils.js'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import { orderReasonLabel } from '../orderConstants.js'
import '../../../core/styles/shared-ui.css'
import '../../../core/styles/order-and-print.css'

// Local YYYY-MM-DD, offset by n days (not toISOString, which is UTC)
const localDate = (n = 0) => {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const STATUS_BADGE = {
  open:       'badge-warning',
  accepted:   'badge-info',
  submitted:  'badge-info',
  shipped:    'badge-info',
  fulfilled:  'badge-success',
  cancelled:  'badge-error',
}

export default function PurchaseOrderHistoryPage() {
  const navigate = useNavigate()
  const { isStoreUser } = useAuth()

  const [orders,    setOrders]    = useState([])
  const [locations, setLocations] = useState([])
  const [vendors,   setVendors]   = useState([])
  const [loading,   setLoading]   = useState(true)
  const [total,     setTotal]     = useState(0)

  // Filters
  const [locationId,  setLocationId]  = useState('')
  const [vendorId,    setVendorId]    = useState('')
  const [status,      setStatus]      = useState('')
  const [isComm,      setIsComm]      = useState('')
  const [orderType,   setOrderType]   = useState('')
  const [dateField,   setDateField]   = useState('order')   // 'order' | 'delivery': filter + sort
  const [dateFrom,    setDateFrom]    = useState('')
  const [dateTo,      setDateTo]      = useState('')
  const [page,        setPage]        = useState(1)
  const PER_PAGE = 20

  const fetchOrders = useCallback(async () => {
    setLoading(true)
    try {
      const params = { page, per_page: PER_PAGE }
      if (locationId) params.location_id   = locationId
      if (vendorId)   params.vendor_id     = vendorId
      if (status)     params.status        = status
      if (isComm)     params.is_commissary = isComm
      if (orderType)  params.order_type    = orderType
      params.date_field = dateField
      if (dateFrom)   params.date_from     = dateFrom
      if (dateTo)     params.date_to       = dateTo
      const res = await axios.get('/api/purchase-orders', { params })
      setOrders(res.data.orders || [])
      setTotal(res.data.total  || 0)
    } catch (e) {
      console.error('Failed to load orders', e)
    } finally {
      setLoading(false)
    }
  }, [locationId, vendorId, status, isComm, orderType, dateField, dateFrom, dateTo, page])

  const fetchStatic = useCallback(async () => {
    try {
      const [locRes, venRes] = await Promise.all([
        axios.get('/api/locations'),
        axios.get('/api/vendors'),
      ])
      setLocations(locRes.data)
      setVendors(venRes.data)
    } catch (e) {
      console.error('Failed to load static data', e)
    }
  }, [])

  useEffect(() => { fetchStatic() }, [fetchStatic])
  useEffect(() => { setPage(1) }, [locationId, vendorId, status, isComm, orderType, dateField, dateFrom, dateTo])
  useEffect(() => { fetchOrders() }, [fetchOrders])


  const pages = Math.ceil(total / PER_PAGE)

  const setDay = (n) => { const d = localDate(n); setDateFrom(d); setDateTo(d) }
  const isDay  = (n) => dateFrom === localDate(n) && dateTo === localDate(n)
  const byDelivery = dateField === 'delivery'

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Order History</h1>
          <p className="page-subtitle">{total} orders</p>
        </div>
        {isStoreUser && (
          <button className="btn btn-primary" onClick={() => navigate('/orders/new')}>
            + Unscheduled Order
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="filter-bar">
        <select className="input filter-select" value={locationId}
          onChange={e => setLocationId(e.target.value)}>
          <option value="">All Locations</option>
          {locations.map(l => (
            <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>
          ))}
        </select>

        <select className="input filter-select" value={vendorId}
          onChange={e => setVendorId(e.target.value)}>
          <option value="">All Vendors</option>
          {vendors.map(v => (
            <option key={v.id} value={v.id}>{v.name}</option>
          ))}
        </select>

        <select className="input filter-select" value={status}
          onChange={e => setStatus(e.target.value)}>
          <option value="">All Statuses</option>
          <option value="open">Open</option>
          <option value="accepted">Accepted</option>
          <option value="shipped">Shipped</option>
          <option value="fulfilled">Fulfilled</option>
          <option value="cancelled">Cancelled</option>
        </select>

        <select className="input filter-select" value={isComm}
          onChange={e => setIsComm(e.target.value)}>
          <option value="">All Types</option>
          <option value="false">Purchase Orders</option>
          <option value="true">Commissary Orders</option>
        </select>

        <select className="input filter-select" value={orderType}
          onChange={e => setOrderType(e.target.value)}>
          <option value="">Scheduled + Unscheduled</option>
          <option value="scheduled">From Order Sheet</option>
          <option value="unscheduled">Unscheduled (catering etc.)</option>
        </select>
      </div>

      {/* Dates: which date to filter + sort by, and the range */}
      <div className="filter-bar po-date-bar">
        <select className="input filter-select" value={dateField}
          onChange={e => setDateField(e.target.value)}>
          <option value="order">By order date</option>
          <option value="delivery">By delivery date</option>
        </select>
        <input className="input po-date-input" type="date" value={dateFrom} aria-label="From"
          onChange={e => setDateFrom(e.target.value)} />
        <span className="po-date-sep">to</span>
        <input className="input po-date-input" type="date" value={dateTo} min={dateFrom || undefined} aria-label="To"
          onChange={e => setDateTo(e.target.value)} />
        <div className="po-date-chips">
          <button className={`btn btn-ghost po-date-chip ${isDay(0) ? 'is-active' : ''}`} onClick={() => setDay(0)}>Today</button>
          <button className={`btn btn-ghost po-date-chip ${isDay(1) ? 'is-active' : ''}`} onClick={() => setDay(1)}>Tomorrow</button>
          {(dateFrom || dateTo) && (
            <button className="btn btn-ghost po-date-chip" onClick={() => { setDateFrom(''); setDateTo('') }}>Clear dates</button>
          )}
        </div>
        {byDelivery && (dateFrom || dateTo) && (
          <span className="po-date-note">Orders with no delivery date are left out</span>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <div className="spinner">Loading orders...</div>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className={!byDelivery ? 'po-sorted' : ''}>Ordered</th>
                  <th className={byDelivery ? 'po-sorted' : ''}>Delivery</th>
                  <th>Location</th>
                  <th>Vendor</th>
                  <th>Type</th>
                  <th>Items</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {orders.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
                      No orders found.
                    </td>
                  </tr>
                ) : orders.map(o => (
                  <tr key={o.id} className="row-link"
                    onClick={() => navigate(`/orders/${o.id}`)}>
                    <td style={{ fontWeight: byDelivery ? 400 : 500 }}>{formatDateShort(o.order_date)}</td>
                    <td style={{ fontWeight: byDelivery ? 500 : 400, color: o.expected_date ? undefined : 'var(--text-muted)' }}>
                      {o.expected_date ? formatDateShort(o.expected_date) : '—'}
                    </td>
                    <td style={{ color: 'var(--text-secondary)' }}>{o.location_name}</td>
                    <td style={{ fontWeight: 500 }}>{o.vendor_name}</td>
                    <td>
                      <span className={`badge ${o.is_commissary ? 'badge-warning' : 'badge-info'}`}>
                        {o.is_commissary ? 'Commissary' : 'Purchase'}
                      </span>
                      {o.order_type === 'unscheduled' && (
                        <span className="badge badge-neutral" style={{ marginLeft: '0.3rem' }}
                          title={o.reference || 'Unscheduled order'}>
                          {orderReasonLabel(o.reason)}
                        </span>
                      )}
                    </td>
                    <td style={{ color: 'var(--text-muted)' }}>
                      {o.line_item_count} items
                    </td>
                    <td>
                      <span className={`badge ${STATUS_BADGE[o.status]}`}>
                        {o.status.charAt(0).toUpperCase() + o.status.slice(1)}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text-muted)' }}>→</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {pages > 1 && (
            <div className="pagination">
              <button className="btn btn-ghost" disabled={page === 1}
                onClick={() => setPage(p => p - 1)}>← Prev</button>
              <span className="pagination-info">Page {page} of {pages}</span>
              <button className="btn btn-ghost" disabled={page === pages}
                onClick={() => setPage(p => p + 1)}>Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
