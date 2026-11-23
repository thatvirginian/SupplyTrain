import { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { formatTimestamp } from '../../../core/utils/dateUtils.js'
import '../../../core/styles/shared-ui.css'
import './OperatorsPage.css'

// Admin → Employee PINs. Only the people given a PIN are kept here. To give
// someone a PIN, pick a location: its employees are read live from Toast (and
// not stored). On a shared login, people clocked in on Toast sign in with their
// name and PIN, and what they submit is signed with their name.

const PIN_LENGTH = 6

function PinDialog({ person, locationId, onClose, onSaved }) {
  const [pin,   setPin]   = useState('')
  const [again, setAgain] = useState('')
  const [error, setError] = useState(null)
  const [busy,  setBusy]  = useState(false)
  const save = async () => {
    if (!new RegExp(`^\\d{${PIN_LENGTH}}$`).test(pin)) return setError(`The PIN must be exactly ${PIN_LENGTH} digits.`)
    if (pin !== again) return setError('The two PINs do not match.')
    setBusy(true)
    try {
      await axios.put('/api/operators/pin', { location_id: locationId, employee_guid: person.employee_guid, pin })
      onSaved()
    } catch (e) {
      setError(e.response?.data?.error || 'Could not save the PIN.')
      setBusy(false)
    }
  }
  const field = (value, set, label) => (
    <div className="form-group">
      <label className="form-label">{label}</label>
      <input className="input ops-pin-input" type="password" inputMode="numeric" maxLength={PIN_LENGTH}
        autoComplete="new-password" value={value}
        onChange={e => set(e.target.value.replace(/\D/g, '').slice(0, PIN_LENGTH))} />
    </div>
  )
  return (
    <div className="ops-overlay" onClick={onClose}>
      <div className="card ops-modal" onClick={e => e.stopPropagation()}>
        <div className="card-header"><h2 className="card-title">{person.pin_id ? 'Change' : 'Give'} PIN · {person.name}</h2></div>
        <div className="card-body">
          {error && <div className="alert alert-error">{error}</div>}
          {field(pin, setPin, `New ${PIN_LENGTH}-digit PIN`)}
          {field(again, setAgain, 'Type it again')}
          <p className="ops-hint">Tell the person their PIN. It cannot be looked up later, only changed.</p>
          <div className="ops-modal-actions">
            <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? 'Saving...' : 'Save PIN'}</button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function OperatorsPage() {
  const [pins,      setPins]      = useState(null)
  const [locations, setLocations] = useState([])
  const [toastOn,   setToastOn]   = useState(null)
  const [error,     setError]     = useState(null)

  const [locationId, setLocationId] = useState('')
  const [employees,  setEmployees]  = useState(null)     // live from Toast for locationId
  const [empError,   setEmpError]   = useState(null)
  const [empLoading, setEmpLoading] = useState(false)
  const [search,     setSearch]     = useState('')
  const [pinFor,     setPinFor]     = useState(null)

  const loadPins = useCallback(async () => {
    try {
      setPins((await axios.get('/api/operators')).data)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not load the PINs.')
    }
  }, [])

  const loadEmployees = useCallback(async () => {
    if (!locationId) { setEmployees(null); return }
    setEmpLoading(true)
    setEmpError(null)
    try {
      setEmployees((await axios.get('/api/operators/toast-employees', { params: { location_id: locationId } })).data)
    } catch (e) {
      setEmployees(null)
      setEmpError(e.response?.data?.error || 'Could not read the employees from Toast.')
    } finally {
      setEmpLoading(false)
    }
  }, [locationId])

  useEffect(() => { loadPins() }, [loadPins])
  useEffect(() => { loadEmployees() }, [loadEmployees])
  useEffect(() => {
    axios.get('/api/locations').then(r => setLocations(r.data)).catch(() => {})
    axios.get('/api/operators/toast-status').then(r => setToastOn(r.data.configured)).catch(() => setToastOn(false))
  }, [])

  const act = async (fn) => {
    setError(null)
    try { await fn(); loadPins(); loadEmployees() } catch (e) { setError(e.response?.data?.error || 'That did not work.') }
  }

  const q = search.trim().toLowerCase()
  const shownEmployees = (employees || []).filter(e => !q || e.name.toLowerCase().includes(q)
    || `${e.first_name || ''} ${e.last_name || ''}`.toLowerCase().includes(q))

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Employee PINs</h1>
          <p className="page-subtitle">
            Toast employees with a PIN can sign their work on a shared login, while clocked in
          </p>
        </div>
      </div>

      {toastOn === false && (
        <div className="alert alert-warning">
          The Toast API is not set up on the server (TOAST_CLIENT_ID and TOAST_CLIENT_SECRET), so employees
          cannot be looked up and clocked-in checks are skipped.
        </div>
      )}
      {error && <div className="alert alert-error">{error}</div>}

      {/* People with a PIN */}
      <div className="card" style={{ marginBottom: '1.25rem' }}>
        <div className="card-header">
          <h2 className="card-title">People with a PIN</h2>
          <span className="ops-sub">{pins ? pins.length : ''}</span>
        </div>
        {pins === null ? <div className="spinner">Loading...</div> : pins.length === 0 ? (
          <div className="card-body ops-sub">Nobody has a PIN yet. Pick a location below to give one.</div>
        ) : (
          <div className="table-wrap" style={{ border: 'none', borderRadius: 0 }}>
            <table>
              <thead>
                <tr><th>Name</th><th>PIN set</th><th>Last signed in</th><th></th></tr>
              </thead>
              <tbody>
                {pins.map(p => (
                  <tr key={p.id}>
                    <td>
                      <div className="ops-name">{p.display_name}</div>
                      <div className="ops-sub">{p.first_name} {p.last_name}</div>
                    </td>
                    <td className="ops-sub">
                      {formatTimestamp(p.pin_set_at)}{p.pin_set_by ? ` · ${p.pin_set_by}` : ''}
                      {p.locked && <span className="badge badge-warning" style={{ marginLeft: '0.4rem' }}>locked</span>}
                    </td>
                    <td className="ops-sub">{p.last_used_at ? formatTimestamp(p.last_used_at) : '—'}</td>
                    <td className="ops-actions">
                      {p.locked && (
                        <button className="btn btn-ghost btn-sm" onClick={() => act(() => axios.post(`/api/operators/${p.id}/unlock`))}>Unlock</button>
                      )}
                      <button className="btn btn-ghost btn-sm" onClick={() => {
                        if (confirm(`Remove ${p.display_name}'s PIN? They are signed out and cannot sign in until they get a new one.`))
                          act(() => axios.delete(`/api/operators/${p.id}`))
                      }}>Remove PIN</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Give a PIN: employees read live from Toast */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Give a PIN</h2>
          <span className="ops-sub">employees are read from Toast, nothing is copied</span>
        </div>
        <div className="card-body">
          <div className="ops-filters">
            <select className="input" style={{ width: 'auto' }} value={locationId}
              onChange={e => { setLocationId(e.target.value); setSearch('') }} disabled={!toastOn}>
              <option value="">Choose a location...</option>
              {locations.map(l => <option key={l.store_guid} value={l.store_guid}>{l.location_name}</option>)}
            </select>
            {employees && (
              <input className="input" style={{ maxWidth: 240 }} placeholder="Search names" value={search}
                onChange={e => setSearch(e.target.value)} />
            )}
            {empLoading && <span className="ops-sub">Asking Toast...</span>}
          </div>
          {empError && <div className="alert alert-error">{empError}</div>}
          {employees && shownEmployees.length === 0 && <div className="ops-sub">No employees match.</div>}
        </div>
        {employees && shownEmployees.length > 0 && (
          <div className="table-wrap" style={{ border: 'none', borderRadius: 0 }}>
            <table>
              <thead><tr><th>Employee</th><th>PIN</th><th></th></tr></thead>
              <tbody>
                {shownEmployees.map(e => (
                  <tr key={e.employee_guid}>
                    <td>
                      <div className="ops-name">{e.name}</div>
                      <div className="ops-sub">{e.first_name} {e.last_name}</div>
                    </td>
                    <td>{e.pin_id ? <span className="badge badge-success">has a PIN</span>
                                  : <span className="ops-sub">—</span>}</td>
                    <td className="ops-actions">
                      <button className="btn btn-ghost btn-sm" onClick={() => setPinFor(e)}>
                        {e.pin_id ? 'Change PIN' : 'Give PIN'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {pinFor && <PinDialog person={pinFor} locationId={locationId} onClose={() => setPinFor(null)}
        onSaved={() => { setPinFor(null); loadPins(); loadEmployees() }} />}
    </div>
  )
}
