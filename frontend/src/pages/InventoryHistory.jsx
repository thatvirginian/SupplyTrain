import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatDate, formatDateShort } from '../utils/dateUtils.js'
import axios from 'axios'
import { useAuth } from '../App.jsx'
import './catalog.css'
import './order-history.css'

const SOURCE_BADGE = {
  count_sheet: 'badge-info',
  manual:      'badge-warning',
}

const STATUS_BADGE = {
  draft:     'badge-warning',
  submitted: 'badge-success',
}

export default function InventoryHistory() {
  const navigate = useNavigate()
  const { isAdmin, isManager } = useAuth()

  const [submissions, setSubmissions] = useState([])
  const [locations,   setLocations]   = useState([])
  const [loading,     setLoading]     = useState(true)
  const [total,       setTotal]       = useState(0)

  const [locationId, setLocationId] = useState('')
  const [source,     setSource]     = useState('')
  const [page,       setPage]       = useState(1)
  const PER_PAGE = 20

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params = { page, per_page: PER_PAGE }
      if (locationId) params.location_id = locationId
      if (source)     params.source      = source
      const res = await axios.get('/api/inventory-submissions', { params })
      setSubmissions(res.data.submissions || [])
      setTotal(res.data.total || 0)
    } catch (e) {
      console.error('Failed to load inventories', e)
    } finally {
      setLoading(false)
    }
  }, [locationId, source, page])

  const fetchLocations = useCallback(async () => {
    try {
      const res = await axios.get('/api/locations')
      setLocations(res.data)
    } catch (e) { console.error('Failed to load locations', e) }
  }, [])

  useEffect(() => { fetchLocations() }, [fetchLocations])
  useEffect(() => { setPage(1) }, [locationId, source])
  useEffect(() => { fetchData() }, [fetchData])


  const pages = Math.ceil(total / PER_PAGE)

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Inventory History</h1>
          <p className="page-subtitle">{total} inventories</p>
        </div>
        {isAdmin && (
          <button className="btn btn-primary"
            onClick={() => navigate('/inventory-templates')}>
            Manage Templates
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="filter-bar">
        {isAdmin && (
          <select className="input filter-select" value={locationId}
            onChange={e => setLocationId(e.target.value)}>
            <option value="">All Locations</option>
            {locations.map(l => (
              <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>
            ))}
          </select>
        )}
        <select className="input filter-select" value={source}
          onChange={e => setSource(e.target.value)}>
          <option value="">All Sources</option>
          <option value="count_sheet">Count Sheet</option>
          <option value="manual">Manual</option>
        </select>
      </div>

      {loading ? (
        <div className="spinner">Loading...</div>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Location</th>
                  <th>Source</th>
                  <th>Template</th>
                  <th>Items</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {submissions.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
                      No inventories found.
                    </td>
                  </tr>
                ) : submissions.map(s => (
                  <tr key={s.id} className="row-link"
                    onClick={() => navigate(`/inventory/${s.id}`)}>
                    <td>{formatDate(s.count_date)}</td>
                    <td style={{ color: 'var(--text-secondary)' }}>{s.location_name}</td>
                    <td>
                      <span className={`badge ${SOURCE_BADGE[s.source]}`}>
                        {s.source === 'count_sheet' ? 'Count Sheet' : 'Manual'}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                      {s.template_name || '—'}
                    </td>
                    <td style={{ color: 'var(--text-muted)' }}>{s.item_count}</td>
                    <td>
                      <span className={`badge ${STATUS_BADGE[s.status]}`}>
                        {s.status.charAt(0).toUpperCase() + s.status.slice(1)}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>→</td>
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
