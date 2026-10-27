import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { Icon } from '../components/icons'
import ManuscriptForm from '../components/ManuscriptForm'
import TwoStage from '../components/TwoStage'
import { EditorialBadge, IsbnBadge, RunStatusBadge } from '../components/status'
import StructureViewer from '../components/StructureViewer'
import VersionsPanel from '../components/VersionsPanel'
import { Alert, Card, Empty, ExtractionBadge, PageHeader, Pager, Pill, Spinner, Tabs, Tag } from '../components/ui'
import { EVENT_LABELS, FIELD_LABELS, INTAKE_LABELS, fmtDate, fmtRelative } from '../labels'
import type { AuditEntry, Manuscript, Options, Page, ScreeningRun, Version } from '../types'

type TabKey = 'screening' | 'ringkasan' | 'metadata' | 'versi' | 'struktur' | 'riwayat'

const BUSY = new Set(['PENDING', 'PROCESSING'])

export default function ManuscriptDetailPage() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as TabKey) ?? 'screening'
  const [m, setM] = useState<Manuscript | null>(null)
  const [options, setOptions] = useState<Options | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .get<Manuscript>(`/manuscripts/${id}`)
      .then((x) => {
        setM(x)
        setError(null)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [id])

  useEffect(() => {
    load()
    api
      .get<Options>('/manuscripts/options')
      .then(setOptions)
      .catch(() => undefined)
  }, [load])

  // Selama ada versi yang sedang dibaca, perbarui status secara berkala.
  const processing = m?.versions.some((v) => BUSY.has(v.extraction_status)) ?? false
  useEffect(() => {
    if (!processing) return
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [processing, load])

  if (error && !m)
    return (
      <div className="container">
        <Alert title="Naskah tidak dapat dibuka">{error}</Alert>
      </div>
    )
  if (!m)
    return (
      <div className="container">
        <Spinner />
      </div>
    )

  const setTab = (k: TabKey) => {
    const next = new URLSearchParams(params)
    next.set('tab', k)
    setParams(next, { replace: true })
  }
  const typeLabel = options?.manuscript_types.find((t) => t.value === m.manuscript_type)?.label ?? m.manuscript_type
  const langLabel = options?.languages.find((t) => t.value === m.language_code)?.label ?? m.language_code
  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: 'screening', label: 'Hasil pemeriksaan' },
    { key: 'ringkasan', label: 'Ringkasan' },
    { key: 'struktur', label: 'Isi naskah' },
    { key: 'versi', label: 'Versi berkas', count: m.versions.length },
    { key: 'metadata', label: 'Metadata & penulis' },
    { key: 'riwayat', label: 'Riwayat' },
  ]

  return (
    <div className="container">
      <div className="small mb">
        <Link to="/naskah">← Semua naskah</Link>
      </div>
      <PageHeader
        eyebrow={<span className="mono">{m.internal_code}</span>}
        title={m.working_title}
        sub={
          <span className="meta-line">
            <span>
              <Icon name="user" size="sm" />
              {m.authors.map((a) => a.author_name).join(', ') || 'Penulis belum diisi'}
            </span>
            <span>
              <Icon name="book" size="sm" />
              {typeLabel}
            </span>
            <span>
              <Icon name="calendar" size="sm" />
              {m.submitted_at ? `Masuk ${fmtDate(m.submitted_at, false)}` : 'Tanggal masuk belum diisi'}
            </span>
            <span>
              <Icon name="users" size="sm" />
              {m.assigned_editor?.full_name ?? 'Editor belum ditugaskan'}
            </span>
          </span>
        }
        actions={
          <div className="row">
            <Pill>{INTAKE_LABELS[m.intake_status] ?? m.intake_status}</Pill>
            <ExtractionBadge status={m.latest_version?.extraction_status} />
            {m.latest_screening && <IsbnBadge value={m.latest_screening.isbn_status} />}
            {m.latest_layout && <EditorialBadge value={m.latest_layout.editorial_status} />}
          </div>
        }
      />
      {m.incomplete_fields.length > 0 && (
        <Alert tone="warn" title="Metadata penerimaan belum lengkap">
          Kosong: {m.incomplete_fields.map((f) => FIELD_LABELS[f] ?? f).join(', ')}.{' '}
          <button className="link" onClick={() => setTab('metadata')}>
            Lengkapi sekarang
          </button>
        </Alert>
      )}
      <Tabs tabs={tabs} active={tab} onChange={setTab} />
      {tab === 'screening' && <ScreeningTab m={m} onTab={setTab} />}
      {tab === 'ringkasan' && <Summary m={m} typeLabel={typeLabel} langLabel={langLabel} onTab={setTab} />}
      {tab === 'metadata' && <MetadataTab m={m} onSaved={setM} />}
      {tab === 'versi' && <VersionsPanel manuscript={m} onChanged={load} />}
      {tab === 'struktur' && <StructureViewer versions={m.versions} />}
      {tab === 'riwayat' && <History manuscriptId={m.id} />}
    </div>
  )
}

function Summary({ m, typeLabel, langLabel, onTab }: { m: Manuscript; typeLabel: string; langLabel: string; onTab: (t: TabKey) => void }) {
  const lv = m.latest_version
  const [v, setV] = useState<Version | null>(null)
  useEffect(() => {
    if (lv)
      api
        .get<Version>(`/versions/${lv.id}`)
        .then(setV)
        .catch(() => undefined)
  }, [lv])
  const s = v?.extraction_summary_json
  return (
    <div className="grid split">
      <Card title="Hasil pembacaan versi terbaru" sub={lv ? `Versi ${lv.version_number} · ${lv.original_filename}` : undefined}>
        {!lv ? (
          <Empty icon="upload" title="Belum ada berkas">
            <button className="link" onClick={() => onTab('versi')}>
              Unggah berkas →
            </button>
          </Empty>
        ) : !s || BUSY.has(lv.extraction_status) ? (
          <Spinner />
        ) : (
          <div className="stack">
            <div className="grid minis">
              <Mini label="Bab" value={s.chapters?.length ?? 0} />
              <Mini label="Halaman" value={s.page_count ?? '—'} />
              <Mini label="Kata" value={(s.word_count ?? 0).toLocaleString('id-ID')} />
              <Mini label="Kualitas baca" value={s.quality ? `${Math.round(s.quality.score)}/100` : '—'} />
            </div>
            {!!s.chapters?.length && (
              <table className="table bordered">
                <thead>
                  <tr>
                    <th>Bab</th>
                    <th>Judul</th>
                    <th className="num">Mulai hal.</th>
                  </tr>
                </thead>
                <tbody>
                  {s.chapters.map((c) => (
                    <tr key={c.block_id}>
                      <td className="nowrap strong">BAB {c.label}</td>
                      <td>{c.title ?? '—'}</td>
                      <td className="num">{(s.page_numbers_reliable ? c.page_number : c.page_estimate) ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div>
              <button className="link" onClick={() => onTab('struktur')}>
                Buka isi naskah →
              </button>
            </div>
          </div>
        )}
      </Card>
      <Card title="Data penerimaan">
        <dl className="facts" style={{ gridTemplateColumns: '120px 1fr' }}>
          <dt>Kode</dt>
          <dd className="mono">{m.internal_code}</dd>
          <dt>Jenis</dt>
          <dd>
            <Tag>{typeLabel}</Tag>
          </dd>
          <dt>Bahasa</dt>
          <dd>{langLabel}</dd>
          <dt>Penulis</dt>
          <dd>{m.authors.map((a) => a.author_name).join(', ') || <span className="muted">Belum diisi</span>}</dd>
          <dt>Editor</dt>
          <dd>{m.assigned_editor?.full_name ?? <span className="muted">Belum ditugaskan</span>}</dd>
          <dt>Dibuat</dt>
          <dd>
            {m.creator.full_name}
            <div className="xs muted">{fmtDate(m.created_at)}</div>
          </dd>
          <dt>Sinopsis</dt>
          <dd className="ink-2">{String(m.metadata_json.synopsis ?? '') || <span className="muted">—</span>}</dd>
        </dl>
      </Card>
    </div>
  )
}

function Mini({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card kpi" style={{ padding: '0.75rem 0.9rem' }}>
      <span className="muted small">{label}</span>
      <span className="kpi-value" style={{ fontSize: '1.4rem' }}>
        {value}
      </span>
    </div>
  )
}

function MetadataTab({ m, onSaved }: { m: Manuscript; onSaved: (m: Manuscript) => void }) {
  const { can } = useAuth()
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState(false)
  const editable = can('manuscript.update')
  if (editing)
    return (
      <Card title="Ubah metadata" sub="Perubahan tercatat di audit log beserta nilai sebelum dan sesudahnya.">
        <ManuscriptForm
          initial={m}
          submitLabel="Simpan perubahan"
          onCancel={() => setEditing(false)}
          onSubmit={async (payload) => {
            const updated = await api.patch<Manuscript>(`/manuscripts/${m.id}`, payload)
            onSaved(updated)
            setEditing(false)
            setSaved(true)
          }}
        />
      </Card>
    )
  return (
    <div className="stack">
      {saved && <Alert tone="ok">Perubahan metadata tersimpan dan tercatat di audit log.</Alert>}
      <Card
        title="Penulis"
        sub="Urutan sesuai yang akan dicantumkan"
        action={
          editable && (
            <button className="sm" onClick={() => setEditing(true)}>
              <Icon name="edit" size="sm" />
              Ubah metadata
            </button>
          )
        }
        flush
      >
        {m.authors.length === 0 ? (
          <Empty icon="user" title="Penulis belum diisi" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 50 }}>#</th>
                <th>Nama</th>
                <th>Afiliasi</th>
                <th>Email</th>
              </tr>
            </thead>
            <tbody>
              {m.authors.map((a) => (
                <tr key={a.id}>
                  <td className="num muted">{a.author_order}</td>
                  <td className="strong">{a.author_name}</td>
                  <td className="ink-2">{a.affiliation ?? '—'}</td>
                  <td className="ink-2">{a.author_email ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}

function History({ manuscriptId }: { manuscriptId: string }) {
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<AuditEntry> | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api
      .get<Page<AuditEntry>>(`/manuscripts/${manuscriptId}/history`, { page })
      .then(setData)
      .catch((e) => setError(errorMessage(e)))
  }, [manuscriptId, page])
  if (error) return <Alert>{error}</Alert>
  if (!data) return <Spinner />
  return (
    <Card title="Riwayat peristiwa" sub="Diambil dari audit log; tidak dapat diubah." flush>
      <ul className="feed">
        {data.items.map((e) => (
          <li key={e.id}>
            <span className="feed-icon">
              <Icon name="activity" />
            </span>
            <div className="feed-text">
              <div>
                <span className="strong">{e.actor_name ?? 'Sistem'}</span>{' '}
                <span className="ink-2">{(EVENT_LABELS[e.event_type] ?? e.event_type).toLowerCase()}</span>
              </div>
              <div className="xs muted">
                {fmtDate(e.created_at)} · {fmtRelative(e.created_at)}
              </div>
            </div>
          </li>
        ))}
      </ul>
      <Pager page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
    </Card>
  )
}

function ScreeningTab({ m, onTab }: { m: Manuscript; onTab: (t: TabKey) => void }) {
  const lv = m.latest_version
  const ready = !!lv && !BUSY.has(lv.extraction_status) && lv.extraction_status !== 'FAILED'
  const [history, setHistory] = useState<ScreeningRun[] | null>(null)

  useEffect(() => {
    api
      .get<ScreeningRun[]>(`/manuscripts/${m.id}/screenings`)
      .then(setHistory)
      .catch(() => setHistory([]))
  }, [m.id])

  if (!lv)
    return (
      <Card>
        <Empty icon="upload" title="Belum ada berkas untuk diperiksa">
          <button className="link" onClick={() => onTab('versi')}>
            Unggah berkas →
          </button>
        </Empty>
      </Card>
    )
  if (lv.extraction_status === 'FAILED') return <Alert title="Berkas versi terbaru gagal dibaca">Unggah versi baru yang dapat dibaca.</Alert>
  return (
    <div className="stack">
      {!ready ? <Spinner /> : <TwoStage versionId={lv.id} ready={ready} />}
      {!!history && history.length > 1 && (
        <Card title="Riwayat pemeriksaan" sub="Hasil lama tetap tersimpan dan tidak berubah saat aturan diperbarui." flush>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Tahap</th>
                  <th>Status</th>
                  <th>Hasil</th>
                  <th className="num">Temuan</th>
                  <th>Waktu</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id}>
                    <td className="num">{h.run_number}</td>
                    <td>{h.scope === 'isbn' ? 'Kelayakan ISBN' : h.scope === 'layout' ? 'Cek layout' : 'Lengkap'}</td>
                    <td>
                      <RunStatusBadge value={h.status} />
                    </td>
                    <td>
                      {h.scope !== 'layout' && <IsbnBadge value={h.isbn_status} />}{' '}
                      {h.scope !== 'isbn' && (
                        <>
                          <EditorialBadge value={h.editorial_status} /> <span className="num strong">{h.total_score ?? ''}</span>
                        </>
                      )}
                    </td>
                    <td className="num">{h.result_summary_json.findings_total ?? '—'}</td>
                    <td className="small muted nowrap">{fmtDate(h.completed_at ?? h.queued_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
