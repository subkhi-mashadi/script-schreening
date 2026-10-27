import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { errorMessage } from '../api'
import { useAuth } from '../auth'
import { Icon } from '../components/icons'
import { Alert } from '../components/ui'

const POINTS = [
  'Setiap temuan menunjuk bab, paragraf, dan halaman yang dapat ditelusuri.',
  'Aturan deterministik dan berversi — tanpa AI, hasil dapat direproduksi.',
  'Pemeriksaan ISBN dipisahkan dari penilaian editorial.',
]

export default function LoginPage() {
  const { user, login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <aside className="login-aside">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="book" />
          </span>
          <div>
            <div className="brand-name">Screening Naskah</div>
            <div className="brand-org" style={{ color: '#9fb3cf' }}>
              PT Dimensi Antara Pustaka
            </div>
          </div>
        </div>
        <div>
          <h2>Pemeriksaan naskah yang konsisten, terukur, dan dapat diaudit.</h2>
          <ul>
            {POINTS.map((p) => (
              <li key={p}>
                <Icon name="checkCircle" />
                {p}
              </li>
            ))}
          </ul>
        </div>
        <p className="xs" style={{ color: '#7f93b0' }}>
          Aplikasi internal. Naskah adalah aset rahasia penerbit dan penulis.
        </p>
      </aside>
      <main className="login-main">
        <form className="login-form" onSubmit={submit}>
          <div>
            <h1>Masuk</h1>
            <p className="sub ink-2" style={{ marginTop: '0.35rem' }}>
              Gunakan akun internal penerbit.
            </p>
          </div>
          {error && <Alert>{error}</Alert>}
          <label className="field">
            <span>Email</span>
            <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          </label>
          <label className="field">
            <span>Kata sandi</span>
            <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          <button className="primary" disabled={busy} style={{ justifyContent: 'center', height: 40 }}>
            {busy ? 'Memproses…' : 'Masuk'}
          </button>
        </form>
      </main>
    </div>
  )
}
