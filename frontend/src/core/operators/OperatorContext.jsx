import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import axios from 'axios'
import { getToken, setToken, setSignInOpener, installOperatorInterceptors } from './operatorSession.js'
import SignInDialog from './SignInDialog.jsx'
import './operators.css'

// Who is signed in on this device (shared logins). Provides:
//   operator      {name, employee_guid} or null
//   shared        true when this login is a location's shared login
//   openSignIn()  opens the sign-in box; resolves when someone signs in
//   signOut()
// Also renders the sign-in box, and <OperatorBar /> shows the current person.

const OperatorContext = createContext({ operator: null, shared: false, openSignIn: () => Promise.reject(), signOut: () => {} })

export function useOperator() {
  return useContext(OperatorContext)
}

installOperatorInterceptors()

export function OperatorProvider({ enabled, children }) {
  const [state,  setState]  = useState({ operator: null, shared: false, location_name: null, loaded: false })
  const [dialog, setDialog] = useState(false)
  const waiters = useRef([])                 // promises waiting for a sign-in

  const refresh = useCallback(async () => {
    if (!enabled) return
    try {
      const res = await axios.get('/api/operator-session')
      setState({ ...res.data, loaded: true })
      if (!res.data.operator && getToken()) setToken(null)     // ended on the server (idle, turned off)
    } catch {
      setState(s => ({ ...s, loaded: true }))
    }
  }, [enabled])

  useEffect(() => { refresh() }, [refresh])

  // Notice a session the server ended for being idle, without a page reload.
  useEffect(() => {
    if (!enabled || !state.operator) return
    const t = setInterval(refresh, 60 * 1000)
    return () => clearInterval(t)
  }, [enabled, state.operator, refresh])

  const openSignIn = useCallback(() => new Promise((resolve, reject) => {
    waiters.current.push({ resolve, reject })
    setDialog(true)
  }), [])

  useEffect(() => {
    setSignInOpener(enabled ? openSignIn : null)
    return () => setSignInOpener(null)
  }, [enabled, openSignIn])

  const handleSignedIn = (token, operator) => {
    setToken(token)
    setState(s => ({ ...s, operator }))
    setDialog(false)
    waiters.current.splice(0).forEach(w => w.resolve(operator))
  }

  const handleClose = () => {
    setDialog(false)
    waiters.current.splice(0).forEach(w => w.reject(new Error('closed')))
  }

  const signOut = useCallback(async () => {
    try { await axios.delete('/api/operator-session') } catch { /* signed out locally anyway */ }
    setToken(null)
    setState(s => ({ ...s, operator: null }))
  }, [])

  return (
    <OperatorContext.Provider value={{ ...state, openSignIn, signOut, refresh }}>
      {children}
      {dialog && <SignInDialog current={state.operator} onSignedIn={handleSignedIn} onClose={handleClose} />}
    </OperatorContext.Provider>
  )
}

// The bar at the top of the page on a shared login (or while someone is signed in).
export function OperatorBar() {
  const { operator, shared, loaded, openSignIn, signOut } = useOperator()
  if (!loaded || (!shared && !operator)) return null
  return (
    <div className={`operator-bar ${operator ? 'is-signed-in' : ''}`}>
      {operator ? <>
        <span className="operator-bar-label">Signed in:</span>
        <strong>{operator.name}</strong>
        <button className="operator-bar-btn" onClick={() => openSignIn().catch(() => {})}>Switch</button>
        <button className="operator-bar-btn" onClick={signOut}>Sign out</button>
      </> : <>
        <span className="operator-bar-label">Nobody is signed in</span>
        <button className="operator-bar-btn is-primary" onClick={() => openSignIn().catch(() => {})}>Sign in</button>
      </>}
    </div>
  )
}
