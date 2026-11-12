import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import axios from 'axios'
import { AuthContext } from './core/auth/AuthContext.js'
import Layout from './core/layout/Layout.jsx'
import ProductListPage from './features/catalog/pages/ProductListPage.jsx'
import ProductDetailPage from './features/catalog/pages/ProductDetailPage.jsx'
import ToastMappingPage from './features/toast_mapping/pages/ToastMappingPage.jsx'
import PurchaseOrderHistoryPage from './features/purchase_orders/pages/PurchaseOrderHistoryPage.jsx'
import PurchaseOrderDetailPage from './features/purchase_orders/pages/PurchaseOrderDetailPage.jsx'
import DashboardPage from './features/dashboard/pages/DashboardPage.jsx'
import VendorItemsPage from './features/catalog/pages/VendorItemsPage.jsx'
import OrderTemplateListPage      from './features/order_sheets/pages/OrderTemplateListPage.jsx'
import OrderTemplateDetailPage from './features/order_sheets/pages/OrderTemplateDetailPage.jsx'
import OrderSheetHomePage from './features/order_sheets/pages/OrderSheetHomePage.jsx'
import OrderSheetPage     from './features/order_sheets/pages/OrderSheetPage.jsx'
import ParLevelsPage from './features/par_levels/pages/ParLevelsPage.jsx'
import CommissaryTemplateListPage      from './features/commissary/pages/CommissaryTemplateListPage.jsx'
import CommissaryTemplateDetailPage from './features/commissary/pages/CommissaryTemplateDetailPage.jsx'
import InventoryHomePage           from './features/inventory/pages/InventoryHomePage.jsx'
import InventoryHistoryPage        from './features/inventory/pages/InventoryHistoryPage.jsx'
import InventoryDetailPage         from './features/inventory/pages/InventoryDetailPage.jsx'
import InventoryCountSheetPage          from './features/inventory/pages/InventoryCountSheetPage.jsx'
import InventoryTemplateListPage      from './features/inventory/pages/InventoryTemplateListPage.jsx'
import InventoryTemplateDetailPage from './features/inventory/pages/InventoryTemplateDetailPage.jsx'

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
              <Route path="dashboard"                        element={<DashboardPage />} />
              <Route path="products"                         element={<ProductListPage />} />
              <Route path="products/:id"                     element={<ProductDetailPage />} />
              <Route path="mapping"                          element={<ToastMappingPage />} />
              <Route path="vendor-items"                     element={<VendorItemsPage />} />
              <Route path="sheet-templates"                  element={<OrderTemplateListPage />} />
              <Route path="sheet-templates/:id"              element={<OrderTemplateDetailPage />} />
              <Route path="par-levels"                       element={<ParLevelsPage />} />
              <Route path="comm-order-templates"             element={<CommissaryTemplateListPage />} />
              <Route path="comm-order-templates/:id"         element={<CommissaryTemplateDetailPage />} />
              <Route path="inventory-templates"      element={<InventoryTemplateListPage />} />
              <Route path="inventory-templates/:id"  element={<InventoryTemplateDetailPage />} />
            </>}

            {/* Store-side routes (admin, gm, store) */}
            {isStoreUser && <>
              <Route path="count-sheets"                     element={<OrderSheetHomePage />} />
              <Route path="count-sheet/:submissionId"        element={<OrderSheetPage />} />
            </>}

            {/* Orders — store side and commissary side */}
            {isAnyStaff && <>
              <Route path="orders/history"                   element={<PurchaseOrderHistoryPage />} />
              <Route path="orders/:id"                       element={<PurchaseOrderDetailPage />} />
              <Route path="inventory"                element={<InventoryHomePage />} />
              <Route path="inventory/history"        element={<InventoryHistoryPage />} />
              <Route path="inventory/entry/:submissionId" element={<InventoryCountSheetPage />} />
              <Route path="inventory/:id"            element={<InventoryDetailPage />} />
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
