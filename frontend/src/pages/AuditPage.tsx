import { Fragment, useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { BarList, ColumnChart } from '../components/charts'
import { Alert, Card, Kpi, PageHeader, Pager, Spinner } from '../components/ui'
import { EVENT_LABELS, ROLE_LABELS, fmtDate } from '../labels'
import type { AuditEntry, Page } from '../types'

export default function AuditPage() {
  const { can } = useAuth()
  const [filters, setFilters] = useState({ event_type: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<AuditEntry> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    if (!can('audit.read')) return
    api
      .get<Page<AuditEntry>>('/audit-logs', { ...filters, page })
      .then(setData)
      .catch((e) => setError(errorMessage(e)))
  }, [filters, page, can])

  if (!can('audit.read')) return <Alert>Anda tidak memiliki izin membaca audit log.</Alert>

  const update = (patch: Partial<typeof filters>) => {
    setFilters((f) => ({ ...f, ...patch }))
    setPage(1)
  }

  return (
    <div className="container">
      <PageHeader title="Audit log" sub="Catatan peristiwa penting bersifat append-only. Pencarian di halaman ini juga tercatat." />
      <AuditSummary />
      {error && <Alert>{error}</Alert>}
      <Card flush>
        <div className="toolbar">
          <select value={filters.event_type} onChange={(e) => update({ event_type: e.target.value })} aria-label="Jenis peristiwa">
            <option value="">Semua peristiwa</option>
            <option value="auth.">Autentikasi</option>
            <option value="access.">Akses ditolak</option>
            <option value="user.">Pengguna</option>
            <option value="manuscript.">Naskah</option>
            <option value="version.">Versi berkas</option>
            <option value="extraction.">Ekstraksi</option>
            <option value="audit.">Pembacaan audit</option>
          </select>
          <input type="date" value={filters.date_from} onChange={(e) => update({ date_from: e.target.value })} aria-label="Sejak" title="Sejak" />
          <input type="date" value={filters.date_to} onChange={(e) => update({ date_to: e.target.value })} aria-label="Sampai" title="Sampai" />
        </div>
        {!data ? (
          <div className="card-body">
            <Spinner />
          </div>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Waktu</th>
                    <th>Peristiwa</th>
                    <th>Pelaku</th>
                    <th>Entitas</th>
                    <th>IP</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((e) => (
                    <Fragment key={e.id}>
                      <tr>
                        <td className="nowrap small ink-2">{fmtDate(e.created_at)}</td>
                        <td>
                          <div className="cell-title">{EVENT_LABELS[e.event_type] ?? e.event_type}</div>
                          <div className="cell-sub mono">{e.event_type}</div>
                        </td>
                        <td>{e.actor_name ?? <span className="muted">Sistem/anonim</span>}</td>
                        <td className="small">
                          {e.entity_type} <span className="mono muted">{e.entity_id?.slice(0, 8)}</span>
                        </td>
                        <td className="mono small">{e.ip_address ?? '—'}</td>
                        <td>
                          {(e.before_json || e.after_json) && (
                            <button className="link" onClick={() => setOpen(open === e.id ? null : e.id)}>
                              {open === e.id ? 'Tutup' : 'Rincian'}
                            </button>
                          )}
                        </td>
                      </tr>
                      {open === e.id && (
                        <tr>
                          <td colSpan={6}>
                            <div className="grid2">
                              <pre>Sebelum: {JSON.stringify(e.before_json, null, 2)}</pre>
                              <pre>Sesudah: {JSON.stringify(e.after_json, null, 2)}</pre>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </div>
  )
}

interface Summary {
  days: number
  total: number
  by_group: Record<string, number>
  daily: { date: string; count: number }[]
  denied: number
  login_failed: number
  decisions: number
  reviews: number
  top_actors: { name: string; role: string; count: number }[]
}

const GROUP_LABELS: Record<string, string> = {
  auth: 'Autentikasi',
  access: 'Akses ditolak',
  user: 'Pengguna',
  manuscript: 'Naskah',
  version: 'Versi berkas',
  extraction: 'Pembacaan',
  screening: 'Screening',
  finding: 'Verifikasi temuan',
  compliance: 'Bukti ISBN',
  rule: 'Aturan',
  rule_set: 'Rule set',
  rubric: 'Rubrik',
  report: 'Laporan',
  audit: 'Pembacaan audit',
}

const DAY = new Intl.DateTimeFormat('id-ID', { day: 'numeric', month: 'short' })

function lastDays(daily: { date: string; count: number }[], n: number) {
  // Lengkapi hari tanpa aktivitas agar sumbu waktu tidak melompat.
  const counts = new Map(daily.map((d) => [d.date, d.count]))
  const today = new Date()
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(today)
    d.setDate(today.getDate() - (n - 1 - i))
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    return { key, label: DAY.format(d), tooltip: d.toLocaleDateString('id-ID', { dateStyle: 'full' }), value: counts.get(key) ?? 0 }
  })
}

function AuditSummary() {
  const [s, setS] = useState<Summary | null>(null)
  const [days, setDays] = useState<ReturnType<typeof lastDays>>([])
  useEffect(() => {
    api
      .get<Summary>('/audit-logs/summary', { days: 30 })
      .then((x) => {
        setS(x)
        setDays(lastDays(x.daily, 30))
      })
      .catch(() => undefined)
  }, [])
  if (!s) return null
  return (
    <div className="stack mb">
      <div className="grid kpis">
        <Kpi label="Peristiwa 30 hari" value={s.total.toLocaleString('id-ID')} icon="activity" tone="brand" />
        <Kpi label="Verifikasi temuan" value={s.reviews} icon="check" foot="Tindakan editor atas temuan" />
        <Kpi label="Keputusan akhir" value={s.decisions} icon="shield" />
        <Kpi label="Akses ditolak" value={s.denied} icon="alert" tone={s.denied ? 'warn' : undefined} foot={`${s.login_failed} login gagal`} />
      </div>
      <div className="grid split">
        <Card title="Aktivitas harian" sub="Jumlah peristiwa tercatat per hari">
          <ColumnChart data={days} unit="peristiwa" tickEvery={5} />
        </Card>
        <Card title="Pelaku teraktif">
          <BarList data={s.top_actors.map((a) => ({ key: a.name, label: `${a.name} · ${ROLE_LABELS[a.role] ?? a.role}`, value: a.count }))} unit="peristiwa" />
          <div className="mt">
            <h3 className="mb">Jenis peristiwa</h3>
            <BarList
              data={Object.entries(s.by_group)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 6)
                .map(([k, v]) => ({ key: k, label: GROUP_LABELS[k] ?? k, value: v }))}
              unit="peristiwa"
            />
          </div>
        </Card>
      </div>
    </div>
  )
}
