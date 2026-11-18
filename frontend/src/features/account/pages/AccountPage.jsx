// =============================================================================
// features/account/pages/AccountPage.jsx      URL: /account
// =============================================================================
// Opened by clicking the name at the bottom of the sidebar (or "Account" on
// phones). Shows who is signed in, their roles and linked store, and a Log out
// button.
//
// Log out goes to Azure's sign-in layer (/.auth/logout), which ends the app
// session and returns to the home page, where the sign-in screen appears.
// =============================================================================
import { useEffect, useState } from 'react'
import axios from 'axios'
import { useAuth } from '../../../core/auth/AuthContext.js'
import './AccountPage.css'

const ROLE_LABELS = {
  admin:         'Admin',
  gm:            'Store GM',
  store:         'Store',
  commissary:    'Commissary',
  commissary_gm: 'Commissary GM',
  readonly:      'Read only',
}

export const LOGOUT_URL = '/.auth/logout?post_logout_redirect_uri=/'

export default function AccountPage() {
  const { user, roles } = useAuth()
  const [store, setStore] = useState(undefined)   // undefined = loading, null = none

  useEffect(() => {
    axios.get('/api/auth/account')
      .then(res => setStore(res.data.location_name || null))
      .catch(() => setStore(null))
  }, [])

  const roleNames = (roles || []).map(r => ROLE_LABELS[r] || r)

  return (
    <div className="page account-page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Account</h1>
          <p className="page-subtitle">Signed in to SupplyTrain</p>
        </div>
      </div>

      <div className="account-card">
        <dl className="account-details">
          <dt>Signed in as</dt>
          <dd>{user.email || user.username}</dd>

          <dt>Role</dt>
          <dd>{roleNames.length ? roleNames.join(', ') : 'No role assigned'}</dd>

          <dt>Store</dt>
          <dd>{store === undefined ? '…' : store || 'Not linked to a store'}</dd>
        </dl>

        <button
          className="btn btn-danger account-logout"
          onClick={() => { window.location.href = LOGOUT_URL }}
        >
          Log out
        </button>
      </div>
    </div>
  )
}
