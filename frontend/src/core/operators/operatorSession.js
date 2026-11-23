// Operator sign-in on a shared login (see backend core/operators.py).
//
// The device keeps the sign-in token in localStorage and sends it on every API
// call (header X-Operator-Session). The server decides who it is and ends it
// after 15 idle minutes. When a signed action answers 428 operator_required,
// the sign-in box opens; once someone signs in, the same call is sent again.
// Closing the box without signing in fails the call with the server's message.

import axios from 'axios'

const TOKEN_KEY = 'operator-session-token'
const HEADER    = 'X-Operator-Session'

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || null } catch { return null }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch { /* private mode: the token lives only as long as the page */ }
  memoryToken = token || null
}

let memoryToken = null
let opener = null           // set by OperatorProvider: () => Promise (resolves on sign-in)
let installed = false

export function setSignInOpener(fn) { opener = fn }

export function installOperatorInterceptors() {
  if (installed) return
  installed = true

  axios.interceptors.request.use(config => {
    const token = getToken() || memoryToken
    if (token) {
      config.headers = config.headers || {}
      config.headers[HEADER] = token
    }
    return config
  })

  axios.interceptors.response.use(undefined, async error => {
    const res = error.response
    const config = error.config
    if (res?.status === 428 && res.data?.code === 'operator_required' && config && !config._operatorRetry && opener) {
      try {
        await opener()
      } catch {
        return Promise.reject(error)        // closed without signing in
      }
      return axios({ ...config, _operatorRetry: true })
    }
    return Promise.reject(error)
  })
}
