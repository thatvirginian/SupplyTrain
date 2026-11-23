import { useState, useEffect, useCallback } from 'react'
import axios from 'axios'

// Sign-in box: tap your name, then your 6-digit PIN.
// The names are the people clocked in here on Toast. Only those an admin gave
// a PIN can sign in. When Toast cannot be asked, everyone with a PIN is shown.

const PIN_LENGTH = 6

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'clear', '0', 'back']

export default function SignInDialog({ current, onSignedIn, onClose }) {
  const [people,  setPeople]  = useState(null)
  const [toast,   setToast]   = useState(null)
  const [error,   setError]   = useState(null)
  const [person,  setPerson]  = useState(null)
  const [pin,     setPin]     = useState('')
  const [busy,    setBusy]    = useState(false)

  useEffect(() => {
    axios.get('/api/operator-sign-in/people')
      .then(res => { setPeople(res.data.people); setToast(res.data.toast) })
      .catch(e => { setPeople([]); setError(e.response?.data?.error || 'Could not load the people who can sign in.') })
  }, [])

  const submit = useCallback(async (code) => {
    setBusy(true)
    setError(null)
    try {
      const res = await axios.post('/api/operator-session', { employee_guid: person.employee_guid, pin: code })
      onSignedIn(res.data.token, res.data.operator)
    } catch (e) {
      const d = e.response?.data || {}
      setError(d.code === 'wrong_pin'
        ? `Wrong PIN. ${d.tries_left} ${d.tries_left === 1 ? 'try' : 'tries'} left.`
        : d.error || 'Could not sign in.')
      setPin('')
    } finally {
      setBusy(false)
    }
  }, [person, onSignedIn])

  const press = (k) => {
    if (busy) return
    if (k === 'clear') return setPin('')
    if (k === 'back')  return setPin(p => p.slice(0, -1))
    if (pin.length >= PIN_LENGTH) return
    const next = pin + k
    setPin(next)
    if (next.length === PIN_LENGTH) submit(next)
  }

  // Typing on a keyboard works too
  useEffect(() => {
    if (!person) return
    const onKey = (e) => {
      if (/^\d$/.test(e.key)) press(e.key)
      else if (e.key === 'Backspace') press('back')
      else if (e.key === 'Escape') setPerson(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })


  return (
    <div className="op-overlay" onClick={onClose}>
      <div className="op-dialog" onClick={e => e.stopPropagation()} role="dialog" aria-label="Sign in">
        <div className="op-dialog-head">
          <div>
            <div className="op-dialog-title">{person ? person.name : 'Who is working?'}</div>
            <div className="op-dialog-sub">
              {person ? `Enter your ${PIN_LENGTH}-digit PIN`
                : current ? `Signed in now: ${current.name}. Tap your name to switch.`
                : 'Tap your name, then enter your PIN.'}
            </div>
          </div>
          <button className="op-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        {error && <div className="op-error">{error}</div>}

        {!person && (
          <div className="op-body">
            {people === null && <div className="op-muted">Loading...</div>}
            {people && people.length === 0 && !error && (
              <div className="op-muted">
                {toast === 'ok' ? 'Nobody is clocked in here on Toast. Clock in first.'
                  : 'Nobody has a PIN yet. An admin gives PINs under Admin → Employee PINs.'}
              </div>
            )}
            {toast !== 'ok' && people?.length > 0 && (
              <div className="op-muted op-small">Toast could not be checked for who is clocked in, so everyone with a PIN is shown.</div>
            )}
            <div className="op-names">
              {people && people.map(p => (
                <button key={p.employee_guid} className={`op-name ${p.has_pin ? '' : 'is-no-pin'}`}
                  disabled={p.locked}
                  onClick={() => {
                    if (!p.has_pin) { setError(`${p.name} does not have a PIN yet. Ask an admin to set one.`); return }
                    setPerson(p); setPin(''); setError(null)
                  }}>
                  {toast === 'ok' && <span className="op-dot" title="Clocked in on Toast" />}
                  {p.name}
                  {p.locked && <span className="op-locked">locked</span>}
                  {!p.has_pin && <span className="op-locked op-no-pin">no PIN</span>}
                </button>
              ))}
            </div>
          </div>
        )}

        {person && (
          <div className="op-body">
            <div className="op-pin-dots">
              {Array.from({ length: PIN_LENGTH }, (_, i) => i).map(i => <span key={i} className={`op-pin-dot ${i < pin.length ? 'is-on' : ''}`} />)}
            </div>
            <div className="op-keypad">
              {KEYS.map(k => (
                <button key={k} className={`op-key ${k.length > 1 ? 'is-small' : ''}`} disabled={busy}
                  onClick={() => press(k)}>
                  {k === 'clear' ? 'Clear' : k === 'back' ? '⌫' : k}
                </button>
              ))}
            </div>
            <button className="op-link" onClick={() => { setPerson(null); setError(null) }}>← Not you? Pick another name</button>
          </div>
        )}
      </div>
    </div>
  )
}
