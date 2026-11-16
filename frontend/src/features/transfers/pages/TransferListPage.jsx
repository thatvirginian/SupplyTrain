// =============================================================================
// features/transfers/pages/TransferListPage.jsx      URL: /transfers
// =============================================================================
// Transfers into and out of the user's store (admin: all stores).
// =============================================================================
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import { formatDateShort } from '../../../core/utils/dateUtils.js'
import '../../../core/styles/shared-ui.css'
import './TransfersPage.css'
import { TRANSFER_STATUS_BADGE, reasonLabel, capitalize } from '../transferConstants.js'

export default function TransferListPage() {
  const navigate    = useNavigate()
  const { isAdmin } = useAuth()

  const [rows,       setRows]       = useState([])
  const [total,      setTotal]      = useState(0)
  const [myLoc,      setMyLoc]      = useState(null)
  const [locations,  setLocations]  = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)

  const [status,     setStatus]     = useState('')
  const [direction,  setDirection]  = useState('')
  const [locationId, setLocationId] = useState('')
  const [page,       setPage]       = useState(1)
  const PER_PAGE = 20

  const fetchRows = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = { page, per_page: PER_PAGE }
      if (status)     params.status      = status
      if (direction)  params.direction   = direction
      if (locationId) params.location_id = locationId
      const res = await axios.get('/api/transfers', { params })
      setRows(res.data.transfers || [])
      setTotal(res.data.total || 0)
      setMyLoc(res.data.my_location_id)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not load transfers.')
    } finally {
      setLoading(false)
    }
  }, [status, direction, locationId, page])

  useEffect(() => {
    if (isAdmin) axios.get('/api/locations').then(r => setLocations(r.data)).catch(() => {})
  }, [isAdmin])
  useEffect(() => { setPage(1) }, [status, direction, locationId])
  useEffect(() => { fetchRows() }, [fetchRows])

  const pages = Math.max(1, Math.ceil(total / PER_PAGE))
  // Admins pick a store to see the incoming/outgoing split
  const showDirection = !isAdmin || !!locationId

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Transfers</h1>
          <p className="page-subtitle">Product sent between stores · {total} transfers</p>
        </div>
        <button className="btn btn-primary" onClick={() => navigate('/transfers/new')}>+ New Transfer</button>
      </div>

      {!isAdmin && !loading && !myLoc && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          Your account is not linked to a store, so there are no transfers to show.
        </div>
      )}
      {error && <div className="alert alert-error" style={{ marginBottom: '1rem' }}>{error}</div>}

      <div className="filter-bar">
        {isAdmin && (
          <select className="input filter-select" value={locationId} onChange={e => setLocationId(e.target.value)}>
            <option value="">All Stores</option>
            {locations.map(l => <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>)}
          </select>
        )}
        {showDirection && (
          <select className="input filter-select" value={direction} onChange={e => setDirection(e.target.value)}>
            <option value="">In and Out</option>
            <option value="incoming">Incoming</option>
            <option value="outgoing">Outgoing</option>
          </select>
        )}
        <select className="input filter-select" value={status} onChange={e => setStatus(e.target.value)}>
          <option value="">All Statuses</option>
          <option value="open">Open</option>
          <option value="sent">Sent</option>
          <option value="received">Received</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {loading ? (
        <div className="spinner">Loading transfers...</div>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>From → To</th>
                  <th>Reason</th>
                  <th>Items</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
                      No transfers found.
                    </td>
                  </tr>
                ) : rows.map(t => {
                  const arriving = myLoc && t.to_location_id === myLoc && t.status === 'sent'
                  return (
                    <tr key={t.id} className={`row-link ${arriving ? 'xfer-arriving' : ''}`}
                      onClick={() => navigate(`/transfers/${t.id}`)}>
                      <td>{formatDateShort(t.transfer_date)}</td>
                      <td>
                        <span className="xfer-route">
                          <span className={t.from_location_id === myLoc ? 'xfer-route-mine' : ''}>{t.from_location_name}</span>
                          <span className="xfer-route-arrow">→</span>
                          <span className={t.to_location_id === myLoc ? 'xfer-route-mine' : ''}>{t.to_location_name}</span>
                        </span>
                      </td>
                      <td style={{ color: 'var(--text-secondary)' }}>{reasonLabel(t.reason) || '—'}</td>
                      <td style={{ color: 'var(--text-muted)' }}>{t.line_item_count} items</td>
                      <td>
                        <span className={`badge ${TRANSFER_STATUS_BADGE[t.status] || 'badge-neutral'}`}>
                          {arriving ? 'Arriving' : capitalize(t.status)}
                        </span>
                      </td>
                      <td style={{ color: 'var(--text-muted)' }}>→</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {pages > 1 && (
            <div className="pagination">
              <button className="btn btn-ghost" disabled={page === 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
              <span className="pagination-info">Page {page} of {pages}</span>
              <button className="btn btn-ghost" disabled={page === pages} onClick={() => setPage(p => p + 1)}>Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
