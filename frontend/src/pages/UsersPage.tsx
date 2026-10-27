import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { Icon } from '../components/icons'
import { Alert, Card, PageHeader, Pill, Spinner } from '../components/ui'
import { ROLE_LABELS, fmtDate, initials } from '../labels'
import type { Page, User } from '../types'

export default function UsersPage() {
  const { can, user: me } = useAuth()
  const [data, setData] = useState<Page<User> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ full_name: '', email: '', role: 'editor', password: '' })
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .get<Page<User>>('/users', { page_size: 200 })
      .then(setData)
      .catch((e) => setError(errorMessage(e)))
  }, [])
  useEffect(load, [load])

  if (!can('user.manage')) return <Alert>Anda tidak memiliki izin mengelola pengguna.</Alert>

  const create = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await api.post('/users', form)
      setNotice(`Akun ${form.email} dibuat.`)
      setForm({ full_name: '', email: '', role: 'editor', password: '' })
      load()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const patch = async (u: User, body: Partial<User> & { password?: string }) => {
    setError(null)
    try {
      await api.patch(`/users/${u.id}`, body)
      load()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="container stack">
      <PageHeader title="Pengguna" sub={data ? `${data.total} akun · hak akses mengikuti peran (least privilege)` : undefined} />
      {error && <Alert>{error}</Alert>}
      {notice && <Alert tone="ok">{notice}</Alert>}
      <Card title="Tambah pengguna" sub="Kata sandi awal minimal 12 karakter; minta pengguna menggantinya setelah login pertama.">
        <form className="toolbar" style={{ padding: 0, border: 'none' }} onSubmit={create}>
          <input placeholder="Nama lengkap" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
          <input type="email" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} aria-label="Peran">
            {Object.entries(ROLE_LABELS).map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
          <input
            type="password"
            placeholder="Kata sandi awal (min. 12)"
            minLength={12}
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
          />
          <button className="primary">
            <Icon name="plus" size="sm" />
            Tambah
          </button>
        </form>
      </Card>
      {!data ? (
        <Spinner />
      ) : (
        <Card title="Daftar akun" flush>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Nama</th>
                  <th>Email</th>
                  <th>Peran</th>
                  <th>Status</th>
                  <th>Dibuat</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <div className="row" style={{ flexWrap: 'nowrap' }}>
                        <span className="avatar">{initials(u.full_name)}</span>
                        <span className="cell-title">{u.full_name}</span>
                      </div>
                    </td>
                    <td className="ink-2">{u.email}</td>
                    <td>
                      <select
                        value={u.role}
                        disabled={u.id === me?.id}
                        onChange={(e) => void patch(u, { role: e.target.value })}
                        aria-label={`Peran ${u.full_name}`}
                      >
                        {Object.entries(ROLE_LABELS).map(([k, l]) => (
                          <option key={k} value={k}>
                            {l}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      {u.is_active ? (
                        <Pill tone="ok" icon="checkCircle">
                          Aktif
                        </Pill>
                      ) : (
                        <Pill tone="bad" icon="xCircle">
                          Nonaktif
                        </Pill>
                      )}
                    </td>
                    <td className="nowrap muted small">{fmtDate(u.created_at, false)}</td>
                    <td>
                      {u.id !== me?.id && (
                        <button className="link" onClick={() => void patch(u, { is_active: !u.is_active })}>
                          {u.is_active ? 'Nonaktifkan' : 'Aktifkan'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-foot">Mengubah peran atau menonaktifkan akun langsung mencabut seluruh sesi aktif pengguna tersebut.</div>
        </Card>
      )}
    </div>
  )
}
