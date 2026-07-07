import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatDate, formatDateShort } from '../utils/dateUtils.js'
import axios from 'axios'
import './catalog.css'
import './order-history.css'

const STATUS_BADGE = {
  draft:      'badge-warning',
  submitted:  'badge-info',
  received:   'badge-success',
  cancelled:  'badge-error',
}

export default function OrderHistory() {
  const navigate = useNavigate()

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
      const res = await axios.get('/api/purchase-orders', { params })
      setOrders(res.data.orders || [])
      setTotal(res.data.total  || 0)
    } catch (e) {
      console.error('Failed to load orders', e)
    } finally {
      setLoading(false)
    }
  }, [locationId, vendorId, status, isComm, page])

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
  useEffect(() => { setPage(1) }, [locationId, vendorId, status, isComm])
  useEffect(() => { fetchOrders() }, [fetchOrders])


  const pages = Math.ceil(total / PER_PAGE)

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Order History</h1>
          <p className="page-subtitle">{total} orders</p>
        </div>
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
          <option value="draft">Draft</option>
          <option value="submitted">Submitted</option>
          <option value="received">Received</option>
          <option value="cancelled">Cancelled</option>
        </select>

        <select className="input filter-select" value={isComm}
          onChange={e => setIsComm(e.target.value)}>
          <option value="">All Types</option>
          <option value="false">Purchase Orders</option>
          <option value="true">Commissary Orders</option>
        </select>
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
                  <th>Date</th>
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
                    <td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
                      No orders found.
                    </td>
                  </tr>
                ) : orders.map(o => (
                  <tr key={o.id} className="row-link"
                    onClick={() => navigate(`/orders/${o.id}`)}>
                    <td>{formatDate(o.order_date)}</td>
                    <td style={{ color: 'var(--text-secondary)' }}>{o.location_name}</td>
                    <td style={{ fontWeight: 500 }}>{o.vendor_name}</td>
                    <td>
                      <span className={`badge ${o.is_commissary ? 'badge-warning' : 'badge-info'}`}>
                        {o.is_commissary ? 'Commissary' : 'Purchase'}
                      </span>
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
