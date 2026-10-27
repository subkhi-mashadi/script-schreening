import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { useSettings } from '../settings'
import { AUTHORITY_LABELS, CATEGORY_LABELS, EDITORIAL_LABELS, SEVERITY_LABELS, TRACK_LABELS, VERIFICATION_LABELS, VERIFY_LABELS, fmtDate } from '../labels'
import type { ComplianceItem, FindingFacets, FindingItem, LayoutSummary, Page, ScoreRow, ScreeningRun } from '../types'
import { Icon } from './icons'
import { ComplianceBadge, EditorialBadge, IsbnBadge, ObservedBadge, RunStatusBadge, SeverityBadge } from './status'
import DecisionPanel from './review/DecisionPanel'
import { ComparisonCard, ManualEvidence, ReportBar, ReviewLog } from './review/Extras'
import { BulkBar, FindingReview } from './review/FindingReview'
import { DecisionBadge } from './status'
import { Alert, Card, Empty, Pager, Pill, Skeleton, Tabs, Tag } from './ui'

type TabKey = 'revisi' | 'isbn' | 'skor' | 'keputusan' | 'tentang'
const SEVERITIES = ['critical', 'major', 'minor', 'info'] as const

export default function ScreeningResult({ run, onRerun, onChanged }: { run: ScreeningRun; onRerun?: () => void; onChanged?: () => void }) {
  const { can } = useAuth()
  const { auto_mode } = useSettings()
  const layoutOnly = run.scope === 'layout'
  const editable = !auto_mode && can('finding.verify') && !['ACCEPTED_FOR_NEXT_STAGE', 'REJECTED'].includes(run.final_decision ?? '')
  const refresh = () => onChanged?.()
  const [tab, setTab] = useState<TabKey>('revisi')
  const [compliance, setCompliance] = useState<ComplianceItem[] | null>(null)
  const [scores, setScores] = useState<ScoreRow[] | null>(null)
  const [facets, setFacets] = useState<FindingFacets | null>(null)
  const [error, setError] = useState<string | null>(null)
  const done = !['QUEUED', 'PROCESSING'].includes(run.status)

  useEffect(() => {
    if (!done) return
    Promise.all([
      api.get<ComplianceItem[]>(`/screenings/${run.id}/compliance`),
      api.get<ScoreRow[]>(`/screenings/${run.id}/scores`),
      api.get<FindingFacets>(`/screenings/${run.id}/findings/facets`),
    ])
      .then(([c, s, f]) => {
        setCompliance(c)
        setScores(s)
        setFacets(f)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [run.id, done, run.recalculated_at, run.final_decision])

  if (!done)
    return (
      <Card>
        <div className="empty">
          <div className="progress">
            <span />
          </div>
          <strong>Sedang memeriksa naskah…</strong>
          <span className="small">
            Menjalankan {run.rule_set.name} versi {run.rule_set.version}. Hasil muncul otomatis.
          </span>
        </div>
      </Card>
    )

  const summary = run.result_summary_json
  const nFindings = summary.findings_total ?? 0
  const nIsbn = compliance?.length ?? 0

  return (
    <div className="stack">
      {error && <Alert>{error}</Alert>}
      {run.error_details && (
        <Alert tone="warn" title="Screening tidak lengkap">
          {run.error_details.message}
        </Alert>
      )}
      {!!summary.rule_errors?.length && (
        <Alert tone="warn" title="Sebagian aturan gagal dijalankan">
          {summary.rule_errors.join(', ')} — kriteria terkait tidak dinilai. Hubungi admin aturan.
        </Alert>
      )}
      {layoutOnly ? (
        <div className="grid split">
          <LayoutFacts layout={summary.layout} />
          <EditorialGate run={run} scores={scores} />
        </div>
      ) : (
        <div className="grid halves">
          <IsbnGate run={run} items={compliance} />
          <EditorialGate run={run} scores={scores} />
        </div>
      )}
      <SeverityStrip
        counts={summary.by_severity ?? {}}
        verification={auto_mode ? undefined : summary.verification}
        decision={auto_mode ? null : run.final_decision}
      />
      <ComparisonCard run={run} />
      <div className="row between">
        <span className="small muted">
          {auto_mode
            ? `Diperiksa otomatis · ${fmtDate(run.completed_at)}`
            : run.recalculated_at
              ? `Dihitung ulang setelah verifikasi editor · ${fmtDate(run.recalculated_at)}`
              : 'Hasil mesin; belum ada verifikasi editor.'}
        </span>
        <ReportBar run={run} />
      </div>

      <div>
        <Tabs
          tabs={[
            { key: 'revisi' as const, label: 'Daftar revisi', count: nFindings },
            ...(layoutOnly ? [] : [{ key: 'isbn' as const, label: 'Checklist ISBN', count: nIsbn }]),
            { key: 'skor' as const, label: 'Rincian skor' },
            ...(auto_mode ? [] : [{ key: 'keputusan' as const, label: 'Keputusan' }]),
            { key: 'tentang' as const, label: 'Tentang hasil ini' },
          ]}
          active={tab}
          onChange={setTab}
        />
        {tab === 'revisi' && <RevisionMap run={run} facets={facets} editable={editable} onChanged={refresh} />}
        {tab === 'isbn' && <IsbnChecklist runId={run.id} items={compliance} editable={editable} onDone={refresh} />}
        {tab === 'keputusan' && <DecisionPanel run={run} onChanged={refresh} />}
        {tab === 'skor' && <ScoreBreakdown run={run} rows={scores} />}
        {tab === 'tentang' && (
          <div className="stack">
            <About run={run} onRerun={onRerun} />
            {!auto_mode && <ReviewLog run={run} />}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Kartu gerbang
// ---------------------------------------------------------------------------

function IsbnGate({ run, items }: { run: ScreeningRun; items: ComplianceItem[] | null }) {
  const counts = useMemo(() => {
    const c = { pass: 0, fail: 0, unknown: 0, na: 0, unverified: 0 }
    for (const i of items ?? []) {
      const observed = i.manual_observed ?? i.observed
      if (observed === 'pass') c.pass++
      else if (observed === 'fail') c.fail++
      else if (observed === 'not_applicable') c.na++
      else c.unknown++
      if (i.result_status !== 'not_applicable' && i.rule_verification_status !== 'verified') c.unverified++
    }
    return c
  }, [items])
  return (
    <Card title="Kepatuhan ISBN & administrasi" sub="Gerbang terpisah dari skor editorial">
      <div className="gate">
        <IsbnBadge value={run.isbn_status} />
        {items ? (
          <ul className="gate-counts">
            <li>
              <span className="dot" style={{ background: 'var(--ok)' }} />
              <span className="num strong">{counts.pass}</span> ditemukan di naskah
            </li>
            <li>
              <span className="dot" style={{ background: 'var(--bad)' }} />
              <span className="num strong">{counts.fail}</span> belum terpenuhi
            </li>
            <li>
              <span className="dot" style={{ background: 'var(--warn)' }} />
              <span className="num strong">{counts.unknown}</span> perlu bukti manual
            </li>
            {counts.na > 0 && (
              <li>
                <span className="dot" style={{ background: 'var(--axis)' }} />
                <span className="num strong">{counts.na}</span> tidak berlaku
              </li>
            )}
          </ul>
        ) : (
          <Skeleton height={70} />
        )}
      </div>
      {counts.unverified > 0 && (
        <p className="gate-note">
          <Icon name="shield" size="sm" />
          {counts.unverified} aturan belum diverifikasi terhadap regulasi resmi oleh pemilik proses, sehingga status belum dapat dinyatakan lulus atau gagal.
        </p>
      )}
    </Card>
  )
}

function EditorialGate({ run, scores }: { run: ScreeningRun; scores: ScoreRow[] | null }) {
  const total = run.total_score !== null ? Number(run.total_score) : null
  const sc = run.result_summary_json.score
  const th = run.rubric?.thresholds ?? {}
  const reasons = sc?.reasons ?? []
  return (
    <Card
      title={run.scope === 'layout' ? 'Skor layout' : 'Skor editorial'}
      sub={run.rubric ? `${run.rubric.name} · versi ${run.rubric.version}` : 'Tidak ada rubrik untuk jenis naskah ini'}
    >
      <div className="gate">
        <div className="score-hero">
          <span className="score-value num">{total !== null ? total.toLocaleString('id-ID', { maximumFractionDigits: 1 }) : '—'}</span>
          <span className="muted">/100</span>
        </div>
        <EditorialBadge value={run.editorial_status} />
      </div>
      {total !== null && <ScoreMeter value={total} thresholds={th} />}
      <p className="gate-note">
        {sc ? (
          <>
            {sc.scored} dari {sc.applicable} kriteria dinilai (cakupan bobot {sc.coverage}%).
            {reasons.includes('OPEN_MAJOR_FINDING') && ' Rekomendasi diturunkan karena masih ada temuan mayor terbuka.'}
            {reasons.includes('OPEN_CRITICAL_FINDING') && ' Rekomendasi dibatasi karena ada temuan kritis terbuka.'}
            {reasons.includes('LOW_COVERAGE') && ' Cakupan di bawah ambang; skor total tidak diterbitkan.'}
          </>
        ) : scores ? (
          'Skor tidak dihitung.'
        ) : null}
      </p>
    </Card>
  )
}

/** Meteran skor dengan penanda ambang (bullet chart sederhana). */
function ScoreMeter({ value, thresholds }: { value: number; thresholds: { pass?: number; minor_revision?: number; major_revision?: number } }) {
  const marks = [
    { v: thresholds.major_revision ?? 55, label: 'Revisi besar' },
    { v: thresholds.minor_revision ?? 70, label: 'Revisi ringan' },
    { v: thresholds.pass ?? 85, label: 'Lanjut' },
  ]
  return (
    <div className="meter" role="img" aria-label={`Skor ${value} dari 100; ambang ${marks.map((m) => `${m.label} ${m.v}`).join(', ')}`}>
      <div className="meter-track">
        <div className="meter-fill" style={{ width: `${value}%` }} />
        {marks.map((m) => (
          <span key={m.v} className="meter-tick" style={{ left: `${m.v}%` }} title={`${m.label} ≥ ${m.v}`} />
        ))}
      </div>
      <div className="meter-labels">
        {marks.map((m) => (
          <span key={m.v} style={{ left: `${m.v}%` }}>
            {m.v}
          </span>
        ))}
      </div>
    </div>
  )
}

function SeverityStrip({
  counts,
  verification,
  decision,
}: {
  counts: Record<string, number>
  verification?: { total: number; reviewed: number }
  decision: string | null
}) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  return (
    <div className="sev-strip">
      <span className="strong">{total} temuan</span>
      {SEVERITIES.map((s) => (
        <span key={s} className="row" style={{ gap: '0.35rem' }}>
          <SeverityBadge value={s} />
          <span className="num strong">{counts[s] ?? 0}</span>
        </span>
      ))}
      {verification && total > 0 && (
        <span className="row" style={{ gap: '0.4rem', marginLeft: 'auto' }}>
          <span className="small muted">Diverifikasi editor</span>
          <span className="mini-track" style={{ width: 90, flex: 'none' }}>
            <span className="mini-fill" style={{ display: 'block', width: `${(verification.reviewed / verification.total) * 100}%` }} />
          </span>
          <span className="num strong small">
            {verification.reviewed}/{verification.total}
          </span>
        </span>
      )}
      {decision && <DecisionBadge value={decision} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Peta revisi
// ---------------------------------------------------------------------------

function RevisionMap({ run, facets, editable, onChanged }: { run: ScreeningRun; facets: FindingFacets | null; editable: boolean; onChanged: () => void }) {
  const [filters, setFilters] = useState({ severity: '', track: '', section_path: '', q: '', verification_status: '' })
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [tick, setTick] = useState(0)
  const reload = () => {
    setTick((t) => t + 1)
    onChanged()
  }
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<FindingItem> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .get<Page<FindingItem>>(`/screenings/${run.id}/findings`, { ...filters, page, page_size: 50 })
      .then(setData)
      .catch((e) => setError(errorMessage(e)))
  }, [run.id, filters, page, tick])

  const update = (patch: Partial<typeof filters>) => {
    setFilters((f) => ({ ...f, ...patch }))
    setPage(1)
  }

  const groups = useMemo(() => {
    const out: { key: string; items: FindingItem[] }[] = []
    for (const f of data?.items ?? []) {
      const key = f.section_path?.split(' > ')[0] ?? 'Seluruh naskah'
      if (out.at(-1)?.key !== key) out.push({ key, items: [] })
      out.at(-1)!.items.push(f)
    }
    return out
  }, [data])

  return (
    <div className="viewer">
      <aside className="card outline" aria-label="Saring temuan">
        <div className="outline-title">Bagian naskah</div>
        <button className={!filters.section_path ? 'active' : ''} onClick={() => update({ section_path: '' })}>
          Semua bagian
        </button>
        {facets?.chapter.map((c) => (
          <button
            key={c.section_path ?? '_doc'}
            className={filters.section_path === (c.section_path ?? '') && c.section_path ? 'active' : ''}
            onClick={() => c.section_path && update({ section_path: c.section_path })}
            disabled={!c.section_path}
          >
            <span className="row between" style={{ flexWrap: 'nowrap' }}>
              <span>{c.section_path ?? 'Seluruh naskah (tanpa lokasi)'}</span>
              <span className="tag">{c.count}</span>
            </span>
          </button>
        ))}
      </aside>

      <div className="card" style={{ minWidth: 0 }}>
        <div className="toolbar">
          <div className="input-icon grow">
            <Icon name="search" size="sm" />
            <input placeholder="Cari temuan" value={filters.q} onChange={(e) => update({ q: e.target.value })} aria-label="Cari temuan" />
          </div>
          <select value={filters.severity} onChange={(e) => update({ severity: e.target.value })} aria-label="Keparahan">
            <option value="">Semua keparahan</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {SEVERITY_LABELS[s]} ({facets?.severity[s] ?? 0})
              </option>
            ))}
          </select>
          {editable && (
            <>
              <select value={filters.verification_status} onChange={(e) => update({ verification_status: e.target.value })} aria-label="Status verifikasi">
                <option value="">Semua status verifikasi</option>
                {Object.entries(VERIFY_LABELS).map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </>
          )}
          <select value={filters.track} onChange={(e) => update({ track: e.target.value })} aria-label="Jalur">
            <option value="">Semua jalur</option>
            {Object.entries(TRACK_LABELS).map(([k, l]) => (
              <option key={k} value={k}>
                {l} ({facets?.track[k] ?? 0})
              </option>
            ))}
          </select>
        </div>
        {error && <Alert>{error}</Alert>}
        {editable && data && data.items.length > 0 && (
          <div className="toolbar small">
            <label className="row">
              <input
                type="checkbox"
                checked={data.items.every((f) => selected.has(f.id))}
                onChange={(e) => setSelected(e.target.checked ? new Set(data.items.map((f) => f.id)) : new Set())}
              />
              Pilih semua di halaman ini
            </label>
            <span className="muted">Verifikasi menilai kebenaran temuan; skor dihitung ulang otomatis oleh sistem.</span>
          </div>
        )}
        {editable && <BulkBar runId={run.id} ids={[...selected]} onDone={reload} onClear={() => setSelected(new Set())} />}
        {!data ? (
          <div className="card-body stack">
            <Skeleton height={80} />
            <Skeleton height={80} />
          </div>
        ) : data.items.length === 0 ? (
          <Empty icon="checkCircle" title={Object.values(filters).some(Boolean) ? 'Tidak ada temuan yang cocok' : 'Tidak ada temuan'}>
            {!Object.values(filters).some(Boolean) && 'Aturan otomatis tidak menemukan masalah. Pemeriksaan editor tetap diperlukan.'}
          </Empty>
        ) : (
          <>
            {groups.map((g) => (
              <Fragment key={g.key}>
                <div className="group-head">{g.key}</div>
                {g.items.map((f) => (
                  <FindingCard
                    key={f.id}
                    f={f}
                    runId={run.id}
                    editable={editable}
                    selected={selected.has(f.id)}
                    onSelect={() => toggle(f.id)}
                    onReviewed={reload}
                  />
                ))}
              </Fragment>
            ))}
            <Pager page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </>
        )}
      </div>
    </div>
  )
}

function FindingCard({
  f,
  runId,
  editable,
  selected,
  onSelect,
  onReviewed,
}: {
  f: FindingItem
  runId: string
  editable: boolean
  selected: boolean
  onSelect: () => void
  onReviewed: () => void
}) {
  const page = f.page_number ? `hal. ${f.page_number}` : f.page_estimate ? `± hal. ${f.page_estimate}` : null
  return (
    <article className={`finding sev-${f.severity} ${f.verification_status === 'FALSE_POSITIVE' ? 'dismissed' : ''}`}>
      <span className="finding-bar" />
      <div className="finding-body">
        <header className="row between">
          <div className="row" style={{ gap: '0.5rem' }}>
            {editable && <input type="checkbox" checked={selected} onChange={onSelect} aria-label={`Pilih temuan ${f.title}`} />}
            <SeverityBadge value={f.severity} />
            <span className="strong">{f.title}</span>
          </div>
          <div className="row xs muted">
            {f.track === 'compliance' && <Tag>ISBN</Tag>}
            <Tag>{CATEGORY_LABELS[f.category] ?? f.category}</Tag>
            <span className="mono">{f.rule_code}</span>
          </div>
        </header>
        <p className="ink-2 small">{f.description}</p>
        {f.evidence_excerpt && <blockquote className="excerpt">{f.evidence_excerpt}</blockquote>}
        {f.suggested_action && (
          <p className="action small">
            <Icon name="chevronRight" size="sm" />
            {f.suggested_action}
          </p>
        )}
        <footer className="loc">
          {f.section_path && <span className="path">{f.section_path}</span>}
          {page && <span>{page}</span>}
          {f.paragraph_id && <span className="mono">{f.paragraph_id}</span>}
          {f.requires_human_verification && (
            <span className="human">
              <Icon name="user" size="sm" /> perlu diperiksa editor
            </span>
          )}
        </footer>
        {(editable || f.verification_status !== 'UNREVIEWED') && <FindingReview runId={runId} f={f} editable={editable} onDone={onReviewed} />}
      </div>
    </article>
  )
}

// ---------------------------------------------------------------------------
// Checklist ISBN
// ---------------------------------------------------------------------------

function IsbnChecklist({ runId, items, editable, onDone }: { runId: string; items: ComplianceItem[] | null; editable: boolean; onDone: () => void }) {
  if (!items) return <Skeleton height={200} />
  return (
    <Card flush>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Persyaratan</th>
              <th>Pengamatan sistem</th>
              <th>Status</th>
              <th>Dasar aturan</th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id}>
                <td style={{ maxWidth: 380 }}>
                  <div className="cell-title">{c.title}</div>
                  {c.explanation && <div className="cell-sub">{c.explanation}</div>}
                  <ManualEvidence runId={runId} c={c} editable={editable} onDone={onDone} />
                </td>
                <td>
                  <ObservedBadge value={c.manual_observed ?? c.observed} />
                  {c.manual_observed && <div className="cell-sub">oleh editor</div>}
                </td>
                <td>
                  <ComplianceBadge value={c.result_status} />
                  {c.blocking && c.result_status !== 'not_applicable' && <div className="cell-sub">Wajib</div>}
                </td>
                <td className="small">
                  <div>{AUTHORITY_LABELS[c.authority_type] ?? c.authority_type}</div>
                  <div className="cell-sub">
                    {c.rule_verification_status === 'verified' ? (
                      <span style={{ color: 'var(--ok-text)' }}>Terverifikasi</span>
                    ) : (
                      <span style={{ color: 'var(--warn-text)' }}>{VERIFICATION_LABELS[c.rule_verification_status] ?? c.rule_verification_status}</span>
                    )}
                    {c.source_url && (
                      <>
                        {' · '}
                        <a href={c.source_url} target="_blank" rel="noreferrer noopener">
                          {c.source_title ?? 'Sumber'}
                        </a>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-foot">Sistem tidak mengirim apa pun ke Perpusnas. Hasil ini membantu memeriksa kelengkapan sebelum pengajuan.</div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Rincian skor
// ---------------------------------------------------------------------------

function ScoreBreakdown({ run, rows }: { run: ScreeningRun; rows: ScoreRow[] | null }) {
  const [open, setOpen] = useState<string | null>(null)
  if (!rows) return <Skeleton height={200} />
  if (!rows.length) return <Empty icon="info" title="Skor tidak dihitung untuk screening ini" />
  const total = rows.find((r) => r.result_type === 'total')
  const crit = rows.filter((r) => r.result_type === 'criterion')
  return (
    <Card flush>
      <div className="card-body" style={{ paddingBottom: 0 }}>
        <p className="small ink-2">
          Skor per kriteria = 100 − potongan dari temuan aturan yang mengukurnya (setiap aturan punya batas potongan). Skor total = Σ bobot × skor / Σ bobot,
          hanya atas kriteria yang dapat dinilai. Kriteria yang tidak berlaku dikeluarkan, tidak diberi nilai penuh.
        </p>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Kriteria</th>
              <th className="num">Bobot</th>
              <th style={{ width: '30%' }}>Skor</th>
              <th className="num">Kontribusi</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {crit.map((r) => {
              const code = r.criterion_code_snapshot ?? ''
              const scoreVal = r.raw_score !== null ? Number(r.raw_score) : null
              return (
                <Fragment key={code}>
                  <tr>
                    <td>
                      <div className="cell-title">{r.criterion_name_snapshot}</div>
                      <div className="cell-sub">{r.explanation}</div>
                    </td>
                    <td className="num">{Number(r.weight_percent)}%</td>
                    <td>
                      {r.scoring_status === 'scored' && scoreVal !== null ? (
                        <div className="row" style={{ flexWrap: 'nowrap' }}>
                          <div className="mini-track">
                            <div className="mini-fill" style={{ width: `${scoreVal}%` }} />
                          </div>
                          <span className="num strong">{scoreVal}</span>
                        </div>
                      ) : (
                        <Pill>{r.scoring_status === 'not_applicable' ? 'Tidak berlaku' : 'Tidak dinilai'}</Pill>
                      )}
                    </td>
                    <td className="num">{r.weighted_contribution !== null ? Number(r.weighted_contribution).toFixed(2) : '—'}</td>
                    <td>
                      {!!r.calculation_details_json.rules?.length && (
                        <button className="link" onClick={() => setOpen(open === code ? null : code)}>
                          {open === code ? 'Tutup' : 'Rincian'}
                        </button>
                      )}
                    </td>
                  </tr>
                  {open === code && (
                    <tr>
                      <td colSpan={5} style={{ background: 'var(--surface-2)' }}>
                        <table className="table bordered">
                          <thead>
                            <tr>
                              <th>Aturan</th>
                              <th className="num">Temuan dihitung</th>
                              <th className="num">Potongan/temuan</th>
                              <th className="num">Batas</th>
                              <th className="num">Potongan</th>
                            </tr>
                          </thead>
                          <tbody>
                            {r.calculation_details_json.rules!.map((d) => (
                              <tr key={d.rule_code}>
                                <td>
                                  <span className="mono xs">{d.rule_code}</span> {d.title}
                                </td>
                                {d.applicable ? (
                                  <>
                                    <td className="num">{d.findings_counted}</td>
                                    <td className="num">{d.deduction_per_finding}</td>
                                    <td className="num">{d.max_deduction}</td>
                                    <td className="num strong">−{d.deduction}</td>
                                  </>
                                ) : (
                                  <td colSpan={4} className="muted">
                                    Tidak berlaku
                                  </td>
                                )}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
          {total && (
            <tfoot>
              <tr>
                <td className="strong">Skor total</td>
                <td className="num">100%</td>
                <td className="strong num">{total.raw_score !== null ? Number(total.raw_score) : 'Tidak diterbitkan'}</td>
                <td className="num" colSpan={2}>
                  <EditorialBadge value={run.editorial_status} />
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      {total && <div className="table-foot">{total.explanation}</div>}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Tentang
// ---------------------------------------------------------------------------

function About({ run, onRerun }: { run: ScreeningRun; onRerun?: () => void }) {
  const { can } = useAuth()
  const th = run.rubric?.thresholds ?? {}
  return (
    <div className="grid split">
      <Card title="Jejak pemeriksaan" sub="Hasil dapat direproduksi dari kombinasi versi berikut">
        <dl className="facts" style={{ gridTemplateColumns: '170px 1fr' }}>
          <dt>Status</dt>
          <dd>
            <RunStatusBadge value={run.status} />
          </dd>
          <dt>Screening ke-</dt>
          <dd>
            {run.run_number} untuk versi berkas {run.version_number}
          </dd>
          <dt>Rule set</dt>
          <dd>
            {run.rule_set.name} v{run.rule_set.version}
          </dd>
          <dt>Rubrik</dt>
          <dd>{run.rubric ? `${run.rubric.name} v${run.rubric.version}` : '—'}</dd>
          <dt>Ambang rekomendasi</dt>
          <dd className="small">
            {EDITORIAL_LABELS.PASS_RECOMMENDED} ≥ {th.pass ?? 85} · {EDITORIAL_LABELS.MINOR_REVISION} ≥ {th.minor_revision ?? 70} ·{' '}
            {EDITORIAL_LABELS.MAJOR_REVISION} ≥ {th.major_revision ?? 55}
          </dd>
          <dt>Mesin</dt>
          <dd className="mono xs">{run.engine_version}</dd>
          <dt>Aturan dijalankan</dt>
          <dd>
            {run.result_summary_json.rules_run ?? 0} ({run.result_summary_json.rules_not_applicable ?? 0} tidak berlaku untuk jenis naskah ini)
          </dd>
          <dt>Selesai</dt>
          <dd>{fmtDate(run.completed_at)}</dd>
        </dl>
        {onRerun && can('screening.run') && (
          <button className="mt" onClick={onRerun}>
            <Icon name="refresh" size="sm" />
            Jalankan ulang dengan aturan terbaru
          </button>
        )}
      </Card>
      <Card title="Batas penggunaan">
        <p className="small ink-2" style={{ lineHeight: 1.6 }}>
          {run.disclaimer}
        </p>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Ringkasan tata letak
// ---------------------------------------------------------------------------

const cm = (v: number) => `${v.toFixed(1).replace('.', ',')} cm`
const pct = (v: number) => `${Math.round(v * 100)}%`

function Bad({ children }: { children: ReactNode }) {
  return <span style={{ color: 'var(--bad-text)' }}>{children}</span>
}

function LayoutFacts({ layout }: { layout?: LayoutSummary | null }) {
  if (!layout) return <Skeleton height={200} />
  if (!layout.supported)
    return (
      <Card title="Tata letak">
        <p className="small muted">{layout.reason ?? 'Informasi tata letak tidak tersedia.'}</p>
      </Card>
    )
  const sizes = layout.page_sizes ?? []
  const m = layout.margins ?? []
  const med = (k: 'top' | 'bottom' | 'left' | 'right') => (m.length ? [...m].sort((a, b) => a[k] - b[k])[Math.floor(m.length / 2)][k] : null)
  const lowImages = (layout.images ?? []).filter((i) => i.dpi !== null && i.dpi < 300).length
  const rows: [string, ReactNode][] = [
    [
      'Ukuran halaman',
      sizes.length ? (
        <>
          {cm(sizes[0].width_cm)} × {cm(sizes[0].height_cm)}
          {sizes.length > 1 && <span style={{ color: 'var(--warn-text)' }}> · {sizes.length} ukuran berbeda</span>}
        </>
      ) : (
        '—'
      ),
    ],
    ['Margin (atas/bawah/kiri/kanan)', m.length ? `${cm(med('top')!)} / ${cm(med('bottom')!)} / ${cm(med('left')!)} / ${cm(med('right')!)}` : '—'],
    [
      'Huruf isi',
      layout.body_fonts?.length
        ? layout.body_fonts
            .slice(0, 2)
            .map((f) => `${f.value} (${pct(f.share)})`)
            .join(', ')
        : '—',
    ],
    ['Ukuran huruf isi', layout.body_sizes?.length ? `${layout.body_sizes[0].value} pt (${pct(layout.body_sizes[0].share)})` : '—'],
    ['Spasi baris', layout.line_spacing?.length ? `${layout.line_spacing[0].value}` : '—'],
    ['Perataan', layout.alignment?.length ? `${layout.alignment[0].value} (${pct(layout.alignment[0].share)})` : '—'],
    ['Nomor halaman', layout.page_numbers?.present ? 'Ada' : <Bad key="pn">Tidak ditemukan</Bad>],
    ['Gambar', `${layout.images?.length ?? 0} gambar${lowImages ? ` · ${lowImages} di bawah 300 dpi` : ''}`],
  ]
  if (layout.fonts_embedded) rows.push(['Font PDF', layout.fonts_embedded.all ? 'Semua tertanam' : <Bad key="fe">Ada font tidak tertanam</Bad>])
  if (layout.pages) rows.unshift(['Jumlah halaman', String(layout.pages)])
  return (
    <Card title="Tata letak terukur" sub={`Dibaca langsung dari berkas ${layout.format?.toUpperCase() ?? ''}`}>
      <dl className="facts" style={{ gridTemplateColumns: '190px 1fr' }}>
        {rows.map(([k, v]) => (
          <Fragment key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </Fragment>
        ))}
      </dl>
    </Card>
  )
}
