import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect, createContext, useContext } from 'react'
import axios from 'axios'
import Layout from './components/Layout.jsx'
import ProductCatalog from './pages/ProductCatalog.jsx'
import ProductDetail from './pages/ProductDetail.jsx'
import ToastMapping from './pages/ToastMapping.jsx'
import OrderHistory from './pages/OrderHistory.jsx'
import OrderDetail from './pages/OrderDetail.jsx'
import Dashboard from './pages/Dashboard.jsx'
import VendorItems from './pages/VendorItems.jsx'
import SheetTemplates      from './pages/SheetTemplates.jsx'
import SheetTemplateDetail from './pages/SheetTemplateDetail.jsx'
import CountSheetHome from './pages/CountSheetHome.jsx'
import CountSheet     from './pages/CountSheet.jsx'
import ParLevels from './pages/ParLevels.jsx'
import CommOrderTemplates      from './pages/CommOrderTemplates.jsx'
import CommOrderTemplateDetail from './pages/CommOrderTemplateDetail.jsx'
import InventoryHome           from './pages/InventoryHome.jsx'
import InventoryHistory        from './pages/InventoryHistory.jsx'
import InventoryDetail         from './pages/InventoryDetail.jsx'
import InventorySheet          from './pages/InventorySheet.jsx'
import InventoryTemplates      from './pages/InventoryTemplates.jsx'
import InventoryTemplateDetail from './pages/InventoryTemplateDetail.jsx'

// ── Auth Context ──────────────────────────────────────────────────────────────
export const AuthContext = createContext(null)
export const useAuth = () => useContext(AuthContext)

function App() {
  const [user, setUser]     = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get('/api/auth/me')
      .then(res => setUser(res.data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        background: '#0f1117',
        color: '#e2e8f0',
        fontFamily: 'system-ui, sans-serif',
        fontSize: '1rem',
        letterSpacing: '0.05em',
      }}>
        Loading...
      </div>
    )
  }

  if (!user) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        background: '#0f1117',
        color: '#e2e8f0',
        fontFamily: 'system-ui, sans-serif',
      }}>
        <p>Unable to load user. Please refresh.</p>
      </div>
    )
  }

  const roles       = user.roles || []
  const isAdmin     = roles.includes('admin')
  const isGM        = roles.includes('gm')
  const isStore     = roles.includes('store')
  const isComm      = roles.includes('commissary')
  const isCommGM    = roles.includes('commissary_gm')
  const isReadonly  = roles.includes('readonly')

  // Composite helpers
  const isStoreUser = isAdmin || isGM || isStore          // store-side access
  const isCommUser  = isAdmin || isCommGM || isComm       // commissary-side access
  const isManager   = isAdmin || isGM || isCommGM         // can edit orders
  const isAnyStaff  = isStoreUser || isCommUser           // any active role

  return (
    <AuthContext.Provider value={{
      user, roles,
      isAdmin, isGM, isStore, isComm, isCommGM, isReadonly,
      isStoreUser, isCommUser, isManager, isAnyStaff,
      // legacy alias
      isStaff: isAnyStaff,
    }}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            {/* Default redirect */}
            <Route index element={
              isAdmin || isGM
                ? <Navigate to="/dashboard" replace />
                : isCommUser
                  ? <Navigate to="/orders/history" replace />
                  : <Navigate to="/count-sheets" replace />
            } />

            {/* Admin only routes */}
            {isAdmin && <>
              <Route path="dashboard"                        element={<Dashboard />} />
              <Route path="products"                         element={<ProductCatalog />} />
              <Route path="products/:id"                     element={<ProductDetail />} />
              <Route path="mapping"                          element={<ToastMapping />} />
              <Route path="vendor-items"                     element={<VendorItems />} />
              <Route path="sheet-templates"                  element={<SheetTemplates />} />
              <Route path="sheet-templates/:id"              element={<SheetTemplateDetail />} />
              <Route path="par-levels"                       element={<ParLevels />} />
              <Route path="comm-order-templates"             element={<CommOrderTemplates />} />
              <Route path="comm-order-templates/:id"         element={<CommOrderTemplateDetail />} />
              <Route path="inventory-templates"      element={<InventoryTemplates />} />
              <Route path="inventory-templates/:id"  element={<InventoryTemplateDetail />} />
            </>}

            {/* Store-side routes (admin, gm, store) */}
            {isStoreUser && <>
              <Route path="count-sheets"                     element={<CountSheetHome />} />
              <Route path="count-sheet/:submissionId"        element={<CountSheet />} />
            </>}

            {/* Orders — store side and commissary side */}
            {isAnyStaff && <>
              <Route path="orders/history"                   element={<OrderHistory />} />
              <Route path="orders/:id"                       element={<OrderDetail />} />
              <Route path="inventory"                element={<InventoryHome />} />
              <Route path="inventory/history"        element={<InventoryHistory />} />
              <Route path="inventory/entry/:submissionId" element={<InventorySheet />} />
              <Route path="inventory/:id"            element={<InventoryDetail />} />
            </>}

            {/* 404 */}
            <Route path="*" element={
              <div className="page-empty">
                <h2>Page not found</h2>
                <p>Check the URL or use the navigation to find what you need.</p>
              </div>
            } />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthContext.Provider>
  )
}

export default App
