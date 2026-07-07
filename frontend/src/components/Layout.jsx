import { useState, useEffect } from 'react'
import { Outlet, NavLink } from 'react-router-dom'
import { useAuth } from '../App.jsx'
import './Layout.css'

function NavItem({ to, label, icon, collapsed }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) => `nav-item ${isActive ? 'nav-item--active' : ''}`}
      title={collapsed ? label : undefined}
    >
      <span className="nav-icon">{icon}</span>
      {!collapsed && <span className="nav-label">{label}</span>}
    </NavLink>
  )
}

export default function Layout() {
  const { user, isAdmin } = useAuth()

  // Persist collapsed state in localStorage
  const [collapsed, setCollapsed] = useState(() => {
    return localStorage.getItem('sidebar-collapsed') === 'true'
  })

  useEffect(() => {
    localStorage.setItem('sidebar-collapsed', collapsed)
  }, [collapsed])

  return (
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
            <NavItem to="/comm-order-templates"  label="Comm Templates"  icon="⊡" collapsed={collapsed} />
            <NavItem to="/products"              label="Products"        icon="⊞" collapsed={collapsed} />
            <NavItem to="/vendor-items"          label="Vendor Items"    icon="⊟" collapsed={collapsed} />
            <NavItem to="/mapping"               label="Toast Mapping"   icon="⇄" collapsed={collapsed} />
            <NavItem to="/par-levels"            label="Par Levels"      icon="⌆" collapsed={collapsed} />
            <NavItem to="/inventory-templates"   label="Inv Templates"   icon="⧈" collapsed={collapsed} />
          </>}

          {!collapsed && <div className="nav-section-label">Inventory</div>}
          <NavItem to="/count-sheets"   label="Order Sheet"    icon="≡" collapsed={collapsed} />
          <NavItem to="/orders/history" label="Order History"  icon="◷" collapsed={collapsed} />
          <NavItem to="/inventory"      label="Inventories"    icon="⧉" collapsed={collapsed} />
        </nav>

        <div className="sidebar-footer">
          {!collapsed && (
            <>
              <span className="sidebar-user">{user.username}</span>
              <span className="sidebar-role">
                {isAdmin ? 'Admin' : 'Staff'}
              </span>
            </>
          )}
        </div>
      </aside>

      {/* ── Main content ── */}
      <main className="main-content">
        <Outlet />
      </main>

    </div>
  )
}
