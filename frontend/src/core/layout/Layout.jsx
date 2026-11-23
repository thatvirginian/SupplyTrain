import { useState, useEffect } from 'react'
import { Outlet, NavLink } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.js'
import './Layout.css'
import { OperatorProvider, OperatorBar } from '../operators/OperatorContext.jsx'

// end: only highlight on this exact URL (not on pages under it, e.g. /usage vs /usage/par-check)
function NavItem({ to, label, icon, collapsed, end = false }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => `nav-item ${isActive ? 'nav-item--active' : ''}`}
      title={collapsed ? label : undefined}
    >
      <span className="nav-icon">{icon}</span>
      {!collapsed && <span className="nav-label">{label}</span>}
    </NavLink>
  )
}

export default function Layout() {
  const { user, isAdmin, isCommGM, isStoreUser, isCommUser, isManager } = useAuth()

  // Commissary-only users (commissary, commissary GM, not admin or store) get
  // their orders and inventories in the Commissary section instead of the
  // store-side Inventory section.
  const isCommissaryOnly = isCommUser && !isAdmin && !isStoreUser

  // Persist collapsed state in localStorage
  const [collapsed, setCollapsed] = useState(() => {
    return localStorage.getItem('sidebar-collapsed') === 'true'
  })

  useEffect(() => {
    localStorage.setItem('sidebar-collapsed', collapsed)
  }, [collapsed])

  return (
    // Operator sign-in (name + PIN on a shared login) for commissary-side users
    <OperatorProvider enabled={isCommUser}>
    <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>

      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-header">
          {!collapsed && (
            <div className="sidebar-header-text">
              <span className="sidebar-logo">Anita's</span>
              <span className="sidebar-sub">Inventory</span>
            </div>
          )}
          <button
            className="sidebar-toggle"
            onClick={() => setCollapsed(c => !c)}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            {collapsed ? '→' : '←'}
          </button>
        </div>

        <nav className="sidebar-nav">
          {isAdmin && <>
            {!collapsed && <div className="nav-section-label">Admin</div>}
            <NavItem to="/dashboard"             label="Dashboard"       icon="◈" collapsed={collapsed} />
            <NavItem to="/sheet-templates"       label="Order Templates" icon="☰" collapsed={collapsed} />
            <NavItem to="/products"              label="Products"        icon="⊞" collapsed={collapsed} />
            <NavItem to="/vendor-items"          label="Vendor Items"    icon="⊟" collapsed={collapsed} />
            <NavItem to="/mapping"               label="Toast Mapping"   icon="⇄" collapsed={collapsed} />
            <NavItem to="/par-levels"            label="Par Levels"      icon="⌆" collapsed={collapsed} />
            <NavItem to="/inventory-templates"   label="Inv Templates"   icon="⧈" collapsed={collapsed} />
            <NavItem to="/operators"             label="Employee PINs"   icon="☺" collapsed={collapsed} />
          </>}

          {isCommUser && <>
            {!collapsed && <div className="nav-section-label">Commissary</div>}
            <NavItem to="/production"            label="Production"      icon="⚒" collapsed={collapsed} />
            <NavItem to="/production-plan"       label="Production Plan" icon="▤" collapsed={collapsed} />
            {(isAdmin || isCommGM) && (
              <NavItem to="/production-templates" label="Prod Templates" icon="⊠" collapsed={collapsed} />
            )}
            {isAdmin && (
              <NavItem to="/comm-order-templates" label="Comm Templates" icon="⊡" collapsed={collapsed} />
            )}
            {isCommissaryOnly && <>
              <NavItem to="/orders/history"  label="Order History"   icon="◷" collapsed={collapsed} />
              <NavItem to="/transfers"       label="Transfers"       icon="⇆" collapsed={collapsed} />
              <NavItem to="/inventory"       label="Inventories"     icon="⧉" collapsed={collapsed} />
              <NavItem to="/inventory/daily" label="Daily Inventory" icon="▦" collapsed={collapsed} />
            </>}
          </>}

          {!isCommissaryOnly && <>
            {!collapsed && <div className="nav-section-label">Inventory</div>}
            <NavItem to="/count-sheets"   label="Order Sheet"    icon="≡" collapsed={collapsed} />
            <NavItem to="/orders/history" label="Order History"  icon="◷" collapsed={collapsed} />
            {isStoreUser && (
              <NavItem to="/orders/new"   label="Unscheduled Order" icon="✚" collapsed={collapsed} />
            )}
            <NavItem to="/transfers"      label="Transfers"      icon="⇆" collapsed={collapsed} />
            <NavItem to="/inventory"      label="Inventories"    icon="⧉" collapsed={collapsed} />
            <NavItem to="/inventory/daily" label="Daily Inventory" icon="▦" collapsed={collapsed} />
          </>}

          {isManager && <>
            {!collapsed && <div className="nav-section-label">Usage</div>}
            <NavItem to="/usage"           label="Usage Report"   icon="∿" collapsed={collapsed} end />
            <NavItem to="/usage/par-check" label="Par Check"      icon="⊿" collapsed={collapsed} />
          </>}

          {/* Phones: the sidebar footer is hidden, so Account sits in the nav row */}
          <div className="nav-mobile-only">
            <NavItem to="/account" label="Account" icon="◉" collapsed={collapsed} />
          </div>
        </nav>

        {/* Click the name to open the Account page (with Log out) */}
        <NavLink
          to="/account"
          className={({ isActive }) => `sidebar-footer ${isActive ? 'sidebar-footer--active' : ''}`}
          title={collapsed ? `${user.username} · Account` : 'Account'}
        >
          {collapsed ? (
            <span className="sidebar-avatar">{(user.username || '?').charAt(0).toUpperCase()}</span>
          ) : (
            <>
              <span className="sidebar-user">{user.username}</span>
              <span className="sidebar-role">
                {isAdmin ? 'Admin' : 'Staff'}
              </span>
            </>
          )}
        </NavLink>
      </aside>

      {/* ── Main content ── */}
      <main className="main-content">
        <OperatorBar />
        <Outlet />
      </main>

    </div>
    </OperatorProvider>
  )
}
