import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../App.jsx'
import './Layout.css'

function NavItem({ to, label, icon }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) => `nav-item ${isActive ? 'nav-item--active' : ''}`}
    >
      <span className="nav-icon">{icon}</span>
      <span className="nav-label">{label}</span>
    </NavLink>
  )
}

export default function Layout() {
  const { user, isAdmin } = useAuth()

  return (
    <div className="app-shell">

      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <span className="sidebar-logo">Anita's</span>
          <span className="sidebar-sub">Inventory</span>
        </div>

        <nav className="sidebar-nav">
          {isAdmin && <>
            <div className="nav-section-label">Admin</div>
            <NavItem to="/dashboard"  label="Dashboard"     icon="◈" />
            <NavItem to="/sheet-templates" label="Order Templates" icon="☰" />
            <NavItem to="/comm-order-templates" label="Comm Templates" icon="⊡"/>
            <NavItem to="/products"   label="Products"      icon="⊞" />
            <NavItem to="/vendor-items" label="Vendor Items" icon="⊟" />
            <NavItem to="/mapping"    label="Toast Mapping"  icon="⇄" />
            <NavItem to="/par-levels" label="Par Levels" icon="⌆"/>
          </>}

          <div className="nav-section-label">Inventory</div>
          <NavItem to="/count-sheets"      label="Order Sheet"    icon="≡" />
          <NavItem to="/orders/history" label="Order History"  icon="◷" />
          <NavItem to="/inventory" label="Inventories" icon="⧉" />
        </nav>

        <div className="sidebar-footer">
          <span className="sidebar-user">{user.username}</span>
          <span className="sidebar-role">
            {isAdmin ? 'Admin' : 'Staff'}
          </span>
        </div>
      </aside>

      {/* ── Main content ── */}
      <main className="main-content">
        <Outlet />
      </main>

    </div>
  )
}
