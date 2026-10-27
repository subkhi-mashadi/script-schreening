import { useState } from 'react'
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { Icon, type IconName } from './components/icons'
import { Spinner } from './components/ui'
import { ROLE_LABELS, initials } from './labels'
import AuditPage from './pages/AuditPage'
import DashboardPage from './pages/DashboardPage'
import LoginPage from './pages/LoginPage'
import ManuscriptDetailPage from './pages/ManuscriptDetailPage'
import ManuscriptFormPage from './pages/ManuscriptFormPage'
import ManuscriptsPage from './pages/ManuscriptsPage'
import QuickCheckPage from './pages/QuickCheckPage'
import RulesPage from './pages/RulesPage'
import UsersPage from './pages/UsersPage'
import { currentTheme, setTheme, type Theme } from './theme'

interface NavItem {
  to: string
  label: string
  icon: IconName
  end?: boolean
  perm?: string
}

function navItems(can: (p: string) => boolean): { label: string; items: NavItem[] }[] {
  const intake = can('manuscript.create')
  const work: NavItem[] = [
    { to: '/', label: 'Cek Naskah', icon: 'upload', end: true, perm: 'manuscript.create' },
    { to: intake || can('rule.manage') ? '/dashboard' : '/', label: 'Dashboard', icon: 'grid', end: true },
    { to: '/naskah', label: 'Naskah', icon: 'book' },
  ]
  const admin: NavItem[] = [
    { to: '/aturan', label: 'Aturan & rubrik', icon: 'layers', perm: 'rule.read' },
    { to: '/pengguna', label: 'Pengguna', icon: 'users', perm: 'user.manage' },
    { to: '/audit', label: 'Audit log', icon: 'shield', perm: 'audit.read' },
  ]
  const allowed = (i: NavItem) => !i.perm || can(i.perm)
  return [
    { label: 'Kerja', items: work.filter(allowed) },
    { label: 'Administrasi', items: admin.filter(allowed) },
  ].filter((g) => g.items.length)
}

function Shell() {
  const { user, loading, logout, can } = useAuth()
  const [open, setOpen] = useState(false)
  const [theme, setThemeState] = useState<Theme>(currentTheme)
  if (loading)
    return (
      <div className="content">
        <Spinner />
      </div>
    )
  if (!user) return <Navigate to="/login" replace />

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    setThemeState(next)
  }

  return (
    <div className={`shell ${open ? 'nav-open' : ''}`}>
      <aside className="sidebar" aria-label="Navigasi utama">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="book" />
          </span>
          <div>
            <div className="brand-name">Screening Naskah</div>
            <div className="brand-org">PT Dimensi Antara Pustaka</div>
          </div>
        </div>
        {navItems(can).map((g) => (
          <nav className="nav" key={g.label} aria-label={g.label}>
            <div className="nav-label">{g.label}</div>
            {g.items.map((i) => (
              <NavLink key={i.label} to={i.to} end={i.end} onClick={() => setOpen(false)}>
                <Icon name={i.icon} />
                {i.label}
              </NavLink>
            ))}
          </nav>
        ))}
        <div className="sidebar-foot">
          <div className="user-card">
            <span className="avatar">{initials(user.full_name)}</span>
            <div className="user-meta">
              <div className="name truncate">{user.full_name}</div>
              <div className="xs muted truncate">{ROLE_LABELS[user.role] ?? user.role}</div>
            </div>
          </div>
          <div className="foot-actions">
            <button className="ghost sm" onClick={toggleTheme} aria-label={theme === 'dark' ? 'Gunakan tema terang' : 'Gunakan tema gelap'}>
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} size="sm" />
              {theme === 'dark' ? 'Terang' : 'Gelap'}
            </button>
            <button className="ghost sm" onClick={() => void logout()}>
              <Icon name="logout" size="sm" />
              Keluar
            </button>
          </div>
        </div>
      </aside>
      {open && <div className="scrim" onClick={() => setOpen(false)} />}
      <div className="main-col">
        <div className="mobile-bar">
          <button className="ghost sm" onClick={() => setOpen(true)} aria-label="Buka menu">
            <Icon name="menu" />
          </button>
          <strong>Screening Naskah</strong>
        </div>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

/** Operator penerimaan langsung masuk ke Cek Naskah; peran lain ke dashboard. */
function Home() {
  const { can } = useAuth()
  if (can('manuscript.create')) return <QuickCheckPage />
  if (can('rule.manage')) return <RulesPage />
  return <DashboardPage />
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Shell />}>
            <Route index element={<Home />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="naskah" element={<ManuscriptsPage />} />
            <Route path="naskah/baru" element={<ManuscriptFormPage />} />
            <Route path="naskah/:id" element={<ManuscriptDetailPage />} />
            <Route path="aturan" element={<RulesPage />} />
            <Route path="pengguna" element={<UsersPage />} />
            <Route path="audit" element={<AuditPage />} />
            <Route path="*" element={<p>Halaman tidak ditemukan.</p>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
