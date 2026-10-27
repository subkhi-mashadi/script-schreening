import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { BarList, ColumnChart, StatusStack, type StackDatum } from '../components/charts'
import { Icon, type IconName } from '../components/icons'
import { Alert, Card, Empty, ExtractionBadge, Kpi, PageHeader, Pill, Skeleton } from '../components/ui'
import { EVENT_LABELS, FIELD_LABELS, fmtDate, fmtRelative } from '../labels'
import type { Options, ScreeningBrief } from '../types'
import { EditorialBadge, IsbnBadge } from '../components/status'

interface Row {
  id: string
  internal_code: string
  working_title: string
  manuscript_type: string
  authors: string[]
  assigned_editor: string | null
  created_at: string
  latest_version: {
    version_number: number
    extraction_status: string
    extraction_quality: number | null
    page_count: number | null
    chapter_count: number
    uploaded_at: string
  } | null
  reasons?: string[]
  missing_fields?: string[]
  screening?: ScreeningBrief | null
  layout?: ScreeningBrief | null
}

interface Dashboard {
  has_access: boolean
  generated_at?: string
  kpi: {
    manuscripts: number
    received_30d: number
    received_prev_30d: number
    versions: number
    ready: number
    needs_attention: number
    avg_quality: number | null
    pages: number
  }
  by_extraction_status: Record<string, number>
  no_version: number
  by_type: Record<string, number>
  by_isbn_status: Record<string, number>
  by_editorial_status: Record<string, number>
  score_buckets: { label: string; count: number }[]
  avg_score: number | null
  not_screened: number
  top_rules: { rule_code: string; title: string; count: number }[]
  awaiting_decision: number
  layout_checked: number
  by_decision: Record<string, number>
  uploads_daily: { date: string; count: number }[]
  attention: Row[]
  recent: Row[]
  activity: { id: string; event_type: string; actor_name: string | null; manuscript_id: string; manuscript_title: string; created_at: string }[]
}

const REASON: Record<string, { label: string; tone: 'warn' | 'bad' | 'neutral'; icon: IconName }> = {
  NO_VERSION: { label: 'Belum ada berkas', tone: 'neutral', icon: 'inbox' },
  EXTRACTION_FAILED: { label: 'Berkas gagal dibaca', tone: 'bad', icon: 'xCircle' },
  EXTRACTION_INCOMPLETE: { label: 'Terbaca sebagian', tone: 'warn', icon: 'alert' },
  INCOMPLETE_METADATA: { label: 'Metadata kurang', tone: 'warn', icon: 'edit' },
  ISBN_FAIL: { label: 'Belum layak ISBN', tone: 'bad', icon: 'shield' },
  EDITORIAL_REVISION: { label: 'Layout perlu revisi besar', tone: 'warn', icon: 'edit' },
}

const EVENT_ICON: Record<string, IconName> = {
  'manuscript.created': 'plus',
  'manuscript.updated': 'edit',
  'version.uploaded': 'upload',
  'version.downloaded': 'download',
  'version.upload_rejected': 'xCircle',
  'extraction.completed': 'checkCircle',
  'extraction.failed': 'xCircle',
  'extraction.requeued': 'refresh',
}

/** Tahap pemeriksaan sesuai PRD §21; hanya yang sudah dibangun ditandai aktif. */
const STAGES: { name: string; note: string; on: boolean }[] = [
  { name: 'Penerimaan naskah', note: 'Unggah berkas', on: true },
  { name: 'Pembacaan berkas', note: 'Bab, halaman, struktur', on: true },
  { name: 'Kelayakan ISBN', note: 'Otomatis saat unggah', on: true },
  { name: 'Cek layout & kerapian', note: 'Atas permintaan', on: true },
]

const DAY_FMT = new Intl.DateTimeFormat('id-ID', { day: 'numeric', month: 'short' })
const DAY_LONG = new Intl.DateTimeFormat('id-ID', { weekday: 'long', day: 'numeric', month: 'long' })

export default function DashboardPage() {
  const { can, user } = useAuth()
  const navigate = useNavigate()
  const [d, setD] = useState<Dashboard | null>(null)
  const [options, setOptions] = useState<Options | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .get<Dashboard>('/dashboard')
      .then((x) => {
        setD(x)
        setError(null)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [])

  useEffect(() => {
    load()
    api
      .get<Options>('/manuscripts/options')
      .then(setOptions)
      .catch(() => undefined)
  }, [load])

  const typeLabel = (v: string) => options?.manuscript_types.find((t) => t.value === v)?.label ?? v
  const quickPath = can('manuscript.create') ? '/' : null

  const header = (
    <PageHeader
      eyebrow={d?.generated_at ? new Intl.DateTimeFormat('id-ID', { dateStyle: 'full' }).format(new Date(d.generated_at)) : 'Dashboard'}
      title={`Selamat datang, ${user?.full_name.split(' ')[0] ?? ''}`}
      sub={d?.generated_at ? `Ringkasan naskah dalam cakupan akses Anda · diperbarui ${fmtDate(d.generated_at)}` : 'Ringkasan naskah dalam cakupan akses Anda'}
      actions={
        <>
          <button onClick={load}>
            <Icon name="refresh" size="sm" />
            Muat ulang
          </button>
          {quickPath && (
            <Link className="button primary" to={quickPath}>
              <Icon name="upload" size="sm" />
              Cek naskah
            </Link>
          )}
        </>
      }
    />
  )

  if (error)
    return (
      <div className="container">
        {header}
        <Alert title="Dashboard tidak dapat dimuat">{error}</Alert>
      </div>
    )
  if (!d)
    return (
      <div className="container">
        {header}
        <DashboardSkeleton />
      </div>
    )
  if (!d.has_access)
    return (
      <div className="container">
        {header}
        <Card>
          <Empty icon="shield" title="Peran Anda belum memiliki akses ke naskah">
            Menu yang tersedia untuk peran ini ada di navigasi samping.
          </Empty>
        </Card>
      </div>
    )

  const k = d.kpi
  const delta = k.received_30d - k.received_prev_30d
  const statusData: StackDatum[] = [
    { key: 'EXTRACTED', label: 'Siap diperiksa', value: d.by_extraction_status.EXTRACTED ?? 0, color: 'var(--ok)', icon: 'checkCircle' },
    { key: 'INCOMPLETE', label: 'Terbaca sebagian', value: d.by_extraction_status.INCOMPLETE ?? 0, color: 'var(--warn)', icon: 'alert' },
    { key: 'FAILED', label: 'Gagal dibaca', value: d.by_extraction_status.FAILED ?? 0, color: 'var(--bad)', icon: 'xCircle' },
    {
      key: 'PROCESSING',
      label: 'Sedang diproses',
      value: (d.by_extraction_status.PROCESSING ?? 0) + (d.by_extraction_status.PENDING ?? 0),
      color: 'var(--neutral-dot)',
      icon: 'clock',
    },
    { key: 'NONE', label: 'Belum ada berkas', value: d.no_version, color: 'var(--axis)', icon: 'inbox' },
  ]
  const editorialData: StackDatum[] = [
    { key: 'PASS_RECOMMENDED', label: 'Direkomendasikan lanjut', value: d.by_editorial_status.PASS_RECOMMENDED ?? 0, color: 'var(--ok)', icon: 'checkCircle' },
    { key: 'MINOR_REVISION', label: 'Revisi ringan', value: d.by_editorial_status.MINOR_REVISION ?? 0, color: 'var(--series-1)', icon: 'edit' },
    { key: 'MAJOR_REVISION', label: 'Revisi besar', value: d.by_editorial_status.MAJOR_REVISION ?? 0, color: 'var(--warn)', icon: 'alert' },
    { key: 'SUBSTANTIAL_REWORK', label: 'Perlu pengerjaan ulang', value: d.by_editorial_status.SUBSTANTIAL_REWORK ?? 0, color: 'var(--bad)', icon: 'xCircle' },
    {
      key: 'OTHER',
      label: 'Belum dapat dinilai',
      value: (d.by_editorial_status.NEEDS_VERIFICATION ?? 0) + (d.by_editorial_status.NOT_SCORABLE ?? 0),
      color: 'var(--axis)',
      icon: 'info',
    },
  ]
  const isbnData: StackDatum[] = [
    { key: 'PASS', label: 'Layak ISBN', value: d.by_isbn_status.PASS ?? 0, color: 'var(--ok)', icon: 'checkCircle' },
    { key: 'NEEDS_VERIFICATION', label: 'Perlu verifikasi', value: d.by_isbn_status.NEEDS_VERIFICATION ?? 0, color: 'var(--warn)', icon: 'shield' },
    { key: 'FAIL', label: 'Belum layak ISBN', value: d.by_isbn_status.FAIL ?? 0, color: 'var(--bad)', icon: 'xCircle' },
    {
      key: 'OTHER',
      label: 'Belum terbaca lengkap',
      value: (d.by_isbn_status.INCOMPLETE ?? 0) + (d.by_isbn_status.NOT_APPLICABLE ?? 0),
      color: 'var(--axis)',
      icon: 'clock',
    },
  ]
  const uploads = d.uploads_daily.map((u) => {
    const date = new Date(`${u.date}T12:00:00`)
    return { key: u.date, label: DAY_FMT.format(date), tooltip: DAY_LONG.format(date), value: u.count }
  })
  const uploads14 = d.uploads_daily.reduce((s, u) => s + u.count, 0)
  const types = Object.entries(d.by_type)
    .sort((a, b) => b[1] - a[1])
    .map(([key, value]) => ({ key, label: typeLabel(key), value }))

  return (
    <div className="container stack">
      {header}

      <div className="grid kpis">
        <Kpi
          label="Total naskah"
          value={k.manuscripts}
          icon="book"
          tone="brand"
          foot={
            <>
              {k.received_30d} masuk 30 hari terakhir{' '}
              {delta !== 0 && (
                <span className={delta > 0 ? 'delta-up' : 'delta-down'}>
                  ({delta > 0 ? '+' : ''}
                  {delta} vs 30 hari sebelumnya)
                </span>
              )}
            </>
          }
        />
        <Kpi label="Layak ISBN" value={d.by_isbn_status.PASS ?? 0} icon="checkCircle" tone="ok" foot="Syarat naskah Perpusnas 11/2025 terpenuhi" />
        <Kpi
          label="Belum layak ISBN"
          value={d.by_isbn_status.FAIL ?? 0}
          icon="xCircle"
          tone={d.by_isbn_status.FAIL ? 'warn' : undefined}
          foot={`${d.by_isbn_status.INCOMPLETE ?? 0} belum terbaca lengkap`}
        />
        <Kpi label="Sudah cek layout" value={d.layout_checked} icon="layers" foot={`dari ${k.manuscripts} naskah`} />
        <Kpi
          label="Rata-rata skor layout"
          value={d.avg_score ?? '—'}
          unit={d.avg_score !== null ? '/100' : undefined}
          icon="activity"
          foot="Tata letak & kerapian teks"
        />
      </div>

      <Card title="Alur pemeriksaan" sub="Tahap 1–3 berjalan otomatis saat unggah; cek layout dijalankan bila diperlukan." flush>
        <div className="pipeline" style={{ gridTemplateColumns: `repeat(${STAGES.length}, minmax(0, 1fr))` }}>
          {STAGES.map((s) => (
            <div key={s.name} className={`stage ${s.on ? 'on' : 'off'}`}>
              <span className="stage-dot">{s.on ? <Icon name="check" size="sm" /> : <Icon name="clock" size="sm" />}</span>
              <div>
                <div className="stage-name">{s.name}</div>
                <div className="stage-note">{s.on ? `Aktif · ${s.note}` : s.note}</div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid split">
        <Card title="Unggahan berkas" sub={`${uploads14} versi dalam 14 hari terakhir`}>
          {uploads14 === 0 ? <Empty icon="upload" title="Belum ada unggahan dalam 14 hari terakhir" /> : <ColumnChart data={uploads} unit="versi" />}
        </Card>
        <Card title="Status pembacaan" sub="Berdasarkan versi terbaru tiap naskah">
          {k.manuscripts === 0 ? (
            <Empty title="Belum ada naskah" />
          ) : (
            <StatusStack
              data={statusData}
              renderLink={(s, label) => (s.key === 'NONE' || s.key === 'PROCESSING' ? label : <Link to={`/naskah?extraction_status=${s.key}`}>{label}</Link>)}
            />
          )}
        </Card>
      </div>

      <div className="grid halves">
        <Card title="Hasil cek layout" sub={`${d.layout_checked} naskah sudah dicek layout`}>
          {k.manuscripts - d.not_screened === 0 ? <Empty icon="layers" title="Belum ada naskah yang dicek layout" /> : <StatusStack data={editorialData} />}
        </Card>
        <Card title="Kelayakan ISBN" sub="Pemeriksaan terbaru tiap naskah">
          {k.manuscripts - d.not_screened === 0 ? <Empty icon="shield" title="Belum ada naskah yang di-screening" /> : <StatusStack data={isbnData} />}
        </Card>
      </div>

      <div className="grid split">
        <Card
          title="Perlu tindakan"
          sub={k.needs_attention > d.attention.length ? `Menampilkan ${d.attention.length} dari ${k.needs_attention}` : undefined}
          action={
            <Link to="/naskah" className="small">
              Semua naskah →
            </Link>
          }
          flush
        >
          {d.attention.length === 0 ? (
            <Empty icon="checkCircle" title="Tidak ada yang perlu ditindaklanjuti">
              Semua naskah sudah punya berkas yang terbaca dan metadata lengkap.
            </Empty>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Naskah</th>
                    <th>Masalah</th>
                    <th>Masuk</th>
                  </tr>
                </thead>
                <tbody>
                  {d.attention.map((r) => (
                    <tr key={r.id} className="clickable" onClick={() => navigate(`/naskah/${r.id}`)}>
                      <td>
                        <div className="cell-title">{r.working_title}</div>
                        <div className="cell-sub">
                          {r.internal_code} · {typeLabel(r.manuscript_type)}
                        </div>
                      </td>
                      <td>
                        <div className="row">
                          {r.reasons?.map((x) => (
                            <Pill key={x} tone={REASON[x]?.tone} icon={REASON[x]?.icon}>
                              {REASON[x]?.label ?? x}
                            </Pill>
                          ))}
                        </div>
                        {!!r.missing_fields?.length && <div className="cell-sub">Kosong: {r.missing_fields.map((f) => FIELD_LABELS[f] ?? f).join(', ')}</div>}
                      </td>
                      <td className="nowrap muted small">{fmtRelative(r.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <div className="stack">
          <Card title="Temuan terbanyak" sub="Aturan yang paling sering memicu revisi">
            {d.top_rules.length ? (
              <BarList data={d.top_rules.map((r) => ({ key: r.rule_code, label: r.title ?? r.rule_code, value: r.count }))} unit="temuan" />
            ) : (
              <Empty icon="checkCircle" title="Belum ada temuan" />
            )}
          </Card>
          <Card title="Jenis naskah" sub={`${types.length} kategori`}>
            {types.length ? <BarList data={types} unit="naskah" /> : <Empty title="Belum ada naskah" />}
          </Card>
        </div>
      </div>

      <div className="grid split">
        <Card title="Naskah terbaru" flush>
          {d.recent.length === 0 ? (
            <Empty title="Belum ada naskah">{quickPath && <Link to={quickPath}>Unggah naskah pertama →</Link>}</Empty>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Naskah</th>
                    <th>Status</th>
                    <th>Kelayakan ISBN</th>
                    <th className="num">Skor layout</th>
                    <th>Masuk</th>
                  </tr>
                </thead>
                <tbody>
                  {d.recent.map((r) => (
                    <tr key={r.id} className="clickable" onClick={() => navigate(`/naskah/${r.id}`)}>
                      <td>
                        <div className="cell-title">{r.working_title}</div>
                        <div className="cell-sub">{r.authors.join(', ') || r.internal_code}</div>
                      </td>
                      <td>
                        <ExtractionBadge status={r.latest_version?.extraction_status} />
                      </td>
                      <td>{r.screening ? <IsbnBadge value={r.screening.isbn_status} /> : <span className="muted">—</span>}</td>
                      <td className="num">
                        {r.layout?.total_score ?? '—'}
                        {r.layout && (
                          <div className="cell-sub">
                            <EditorialBadge value={r.layout.editorial_status} />
                          </div>
                        )}
                      </td>
                      <td className="nowrap muted small">{fmtRelative(r.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title="Aktivitas terbaru" flush>
          {d.activity.length === 0 ? (
            <Empty icon="activity" title="Belum ada aktivitas" />
          ) : (
            <ul className="feed">
              {d.activity.map((a) => (
                <li key={a.id}>
                  <span className="feed-icon">
                    <Icon name={EVENT_ICON[a.event_type] ?? 'activity'} />
                  </span>
                  <div className="feed-text">
                    <div>
                      <span className="strong">{a.actor_name ?? 'Sistem'}</span>{' '}
                      <span className="ink-2">{(EVENT_LABELS[a.event_type] ?? a.event_type).toLowerCase()}</span>
                    </div>
                    <div className="truncate">
                      <Link to={`/naskah/${a.manuscript_id}`}>{a.manuscript_title}</Link>
                    </div>
                    <div className="xs muted">{fmtRelative(a.created_at)}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <div className="stack" aria-busy="true">
      <div className="grid kpis">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="card kpi">
            <Skeleton width="60%" />
            <Skeleton height={34} width="40%" />
            <Skeleton height={12} width="80%" />
          </div>
        ))}
      </div>
      <Skeleton height={90} />
      <div className="grid split">
        <Skeleton height={260} />
        <Skeleton height={260} />
      </div>
    </div>
  )
}
