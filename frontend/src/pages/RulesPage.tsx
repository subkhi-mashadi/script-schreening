import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, ApiError, errorMessage } from '../api'
import { useAuth } from '../auth'
import { Icon } from '../components/icons'
import { ComplianceBadge, EditorialBadge, IsbnBadge, SeverityBadge } from '../components/status'
import { Alert, Card, Empty, PageHeader, Pill, Spinner, Tabs, Tag } from '../components/ui'
import { AUTHORITY_LABELS, CATEGORY_LABELS, SEVERITY_LABELS, TRACK_LABELS, VERIFICATION_LABELS, fmtDate } from '../labels'
import type { Options, RubricItem, RuleItem, RuleSetItemOut } from '../types'

type TabKey = 'aturan' | 'ruleset' | 'rubrik'

function problems(e: unknown): string {
  if (e instanceof ApiError) {
    const p = (e.details as { problems?: string[] } | undefined)?.problems
    if (p?.length) return `${e.message} ${p.join(' · ')}`
  }
  return errorMessage(e)
}

export default function RulesPage() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as TabKey) ?? 'aturan'
  if (!can('rule.read')) return <Alert>Anda tidak memiliki izin melihat aturan.</Alert>
  return (
    <div className="container">
      <PageHeader
        title="Aturan & rubrik"
        sub="Aturan dan rubrik berversi. Perubahan baru berlaku setelah rule set/rubrik versi baru diuji dan diterbitkan; hasil screening lama tidak berubah."
      />
      <Tabs
        tabs={[
          { key: 'aturan', label: 'Aturan' },
          { key: 'ruleset', label: 'Versi rule set' },
          { key: 'rubrik', label: 'Rubrik skor' },
        ]}
        active={tab}
        onChange={(k) => setParams({ tab: k }, { replace: true })}
      />
      {tab === 'aturan' && <RulesTab />}
      {tab === 'ruleset' && <RuleSetsTab />}
      {tab === 'rubrik' && <RubricsTab />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Aturan
// ---------------------------------------------------------------------------

function RulesTab() {
  const { can } = useAuth()
  const [rules, setRules] = useState<RuleItem[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .get<RuleItem[]>('/rules')
      .then(setRules)
      .catch((e) => setError(errorMessage(e)))
  }, [])
  useEffect(load, [load])

  if (!rules) return <Spinner />
  const unverified = rules.filter((r) => r.authority_type !== 'editorial_indicator' && r.verification_status !== 'verified' && r.status === 'active').length

  return (
    <div className="stack">
      {error && <Alert>{error}</Alert>}
      {notice && (
        <Alert tone="ok" title="Tersimpan">
          {notice}
        </Alert>
      )}
      {unverified > 0 && (
        <Alert tone="warn" title={`${unverified} aturan resmi/kebijakan belum diverifikasi`}>
          Selama belum diverifikasi, aturan tersebut menghasilkan status "perlu verifikasi", bukan lulus/gagal. Verifikasi terhadap teks regulasi/prosedur resmi
          yang berlaku, isi rujukan pasal, lalu terbitkan rule set versi baru.
        </Alert>
      )}
      {(['compliance', 'editorial'] as const).map((track) => (
        <Card key={track} title={TRACK_LABELS[track]} sub={`${rules.filter((r) => r.track === track).length} aturan`} flush>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Aturan</th>
                  <th>Dasar</th>
                  <th>Keparahan</th>
                  <th>Dampak skor</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rules
                  .filter((r) => r.track === track)
                  .map((r) => (
                    <Fragment key={r.id}>
                      <tr className="clickable" onClick={() => setOpen(open === r.id ? null : r.id)}>
                        <td style={{ maxWidth: 420 }}>
                          <div className="cell-title">{r.title}</div>
                          <div className="cell-sub">
                            <span className="mono">{r.rule_code}</span> · {CATEGORY_LABELS[r.category] ?? r.category}
                            {r.applies_to_types && ` · khusus ${r.applies_to_types.length} jenis naskah`}
                          </div>
                        </td>
                        <td className="small">
                          <div>{AUTHORITY_LABELS[r.authority_type]}</div>
                          {r.authority_type !== 'editorial_indicator' && (
                            <Pill tone={r.verification_status === 'verified' ? 'ok' : r.verification_status === 'rejected' ? 'bad' : 'warn'}>
                              {VERIFICATION_LABELS[r.verification_status]}
                            </Pill>
                          )}
                        </td>
                        <td>
                          <SeverityBadge value={r.severity} />
                          {r.blocking && <div className="cell-sub">Wajib (blocking)</div>}
                        </td>
                        <td className="small ink-2">
                          {r.scoring_effect?.criterion_code
                            ? `−${r.scoring_effect.deduction_per_finding}/temuan, maks ${r.scoring_effect.max_deduction}`
                            : track === 'compliance'
                              ? 'Gerbang terpisah'
                              : '—'}
                        </td>
                        <td>{r.status === 'active' ? <Pill tone="ok">Aktif</Pill> : <Pill>Nonaktif</Pill>}</td>
                        <td>
                          <Icon name={open === r.id ? 'chevronDown' : 'chevronRight'} size="sm" />
                        </td>
                      </tr>
                      {open === r.id && (
                        <tr>
                          <td colSpan={6} style={{ background: 'var(--surface-2)' }}>
                            <RuleEditor
                              rule={r}
                              editable={can('rule.manage')}
                              onSaved={(msg) => {
                                setNotice(msg)
                                load()
                              }}
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </div>
  )
}

function RuleEditor({ rule, editable, onSaved }: { rule: RuleItem; editable: boolean; onSaved: (msg: string) => void }) {
  const [form, setForm] = useState({
    title: rule.title,
    severity: rule.severity,
    blocking: rule.blocking,
    requires_human_verification: rule.requires_human_verification,
    status: rule.status,
    source_title: rule.source_title ?? '',
    source_url: rule.source_url ?? '',
    source_reference: rule.source_reference ?? '',
    deduction: String(rule.scoring_effect?.deduction_per_finding ?? ''),
    cap: String(rule.scoring_effect?.max_deduction ?? ''),
    config: JSON.stringify(rule.config_json, null, 2),
  })
  const [verify, setVerify] = useState({ status: rule.verification_status === 'verified' ? 'verified' : 'verified', note: '' })
  const [error, setError] = useState<string | null>(null)
  const official = rule.authority_type !== 'editorial_indicator'

  const save = async () => {
    setError(null)
    let config: unknown
    try {
      config = JSON.parse(form.config)
    } catch {
      setError('Konfigurasi bukan JSON yang valid.')
      return
    }
    try {
      await api.patch(`/rules/${rule.id}`, {
        title: form.title,
        severity: form.severity,
        blocking: form.blocking,
        requires_human_verification: form.requires_human_verification,
        status: form.status,
        source_title: form.source_title || null,
        source_url: form.source_url || null,
        source_reference: form.source_reference || null,
        config_json: config,
        ...(rule.scoring_effect?.criterion_code
          ? {
              scoring_effect: {
                ...rule.scoring_effect,
                deduction_per_finding: Number(form.deduction),
                max_deduction: Number(form.cap),
              },
            }
          : {}),
      })
      onSaved(`${rule.rule_code} diperbarui. Buat dan terbitkan rule set versi baru agar perubahan dipakai screening.`)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const sendVerification = async () => {
    setError(null)
    try {
      await api.post(`/rules/${rule.id}/verification`, { verification_status: verify.status, note: verify.note })
      onSaved(`Status verifikasi ${rule.rule_code}: ${VERIFICATION_LABELS[verify.status]}. Terbitkan rule set versi baru agar berlaku.`)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <div className="stack" style={{ padding: '0.5rem 0' }}>
      {rule.description && <p className="small ink-2">{rule.description}</p>}
      {error && <Alert>{error}</Alert>}
      <div className="grid2">
        <label className="field">
          <span>Judul aturan</span>
          <input value={form.title} disabled={!editable} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </label>
        <div className="grid2">
          <label className="field">
            <span>Keparahan</span>
            <select value={form.severity} disabled={!editable} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
              {Object.entries(SEVERITY_LABELS).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Status</span>
            <select value={form.status} disabled={!editable} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              <option value="active">Aktif</option>
              <option value="retired">Nonaktif</option>
            </select>
          </label>
        </div>
        {rule.scoring_effect?.criterion_code && (
          <div className="grid2">
            <label className="field">
              <span>Potongan per temuan</span>
              <input type="number" min={0} value={form.deduction} disabled={!editable} onChange={(e) => setForm({ ...form, deduction: e.target.value })} />
            </label>
            <label className="field">
              <span>Batas potongan</span>
              <input type="number" min={0} value={form.cap} disabled={!editable} onChange={(e) => setForm({ ...form, cap: e.target.value })} />
            </label>
          </div>
        )}
        <div className="row">
          <label className="row small">
            <input type="checkbox" checked={form.blocking} disabled={!editable} onChange={(e) => setForm({ ...form, blocking: e.target.checked })} />
            Wajib (blocking)
          </label>
          <label className="row small">
            <input
              type="checkbox"
              checked={form.requires_human_verification}
              disabled={!editable}
              onChange={(e) => setForm({ ...form, requires_human_verification: e.target.checked })}
            />
            Selalu perlu verifikasi manusia
          </label>
        </div>
      </div>
      {official && (
        <div className="grid2">
          <label className="field">
            <span>Sumber</span>
            <input value={form.source_title} disabled={!editable} onChange={(e) => setForm({ ...form, source_title: e.target.value })} />
          </label>
          <label className="field">
            <span>URL sumber</span>
            <input value={form.source_url} disabled={!editable} onChange={(e) => setForm({ ...form, source_url: e.target.value })} />
          </label>
          <label className="field" style={{ gridColumn: '1 / -1' }}>
            <span>
              Rujukan pasal/ketentuan <span className="hint">wajib sebelum diverifikasi</span>
            </span>
            <input value={form.source_reference} disabled={!editable} onChange={(e) => setForm({ ...form, source_reference: e.target.value })} />
          </label>
        </div>
      )}
      <label className="field">
        <span>
          Konfigurasi (JSON) <span className="hint">mesin: {rule.engine_key}</span>
        </span>
        <textarea className="code-block" value={form.config} disabled={!editable} onChange={(e) => setForm({ ...form, config: e.target.value })} />
      </label>
      {editable && (
        <div className="row">
          <button className="primary" onClick={() => void save()}>
            Simpan aturan
          </button>
          <span className="muted small">Perubahan sumber/konfigurasi aturan resmi membatalkan verifikasinya.</span>
        </div>
      )}
      {official && editable && (
        <Card title="Verifikasi sumber resmi" sub={rule.verification_note ? `Catatan terakhir: ${rule.verification_note}` : undefined}>
          <div className="toolbar" style={{ padding: 0, border: 'none' }}>
            <select value={verify.status} onChange={(e) => setVerify({ ...verify, status: e.target.value })} aria-label="Status verifikasi">
              <option value="verified">Terverifikasi</option>
              <option value="unverified">Belum diverifikasi</option>
              <option value="rejected">Ditolak (tidak sesuai regulasi)</option>
            </select>
            <input
              className="grow"
              placeholder="Catatan: dokumen, tanggal akses, penanggung jawab"
              value={verify.note}
              onChange={(e) => setVerify({ ...verify, note: e.target.value })}
            />
            <button onClick={() => void sendVerification()} disabled={verify.note.trim().length < 5}>
              <Icon name="shield" size="sm" />
              Simpan verifikasi
            </button>
          </div>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Rule set
// ---------------------------------------------------------------------------

interface SimResult {
  file: string
  isbn_status: string
  findings_total: number
  rubric: string | null
  score: { total: number | null; editorial_status: string; coverage: number } | null
  compliance: { rule_code: string; title: string; observed: string | null; result_status: string }[]
  rules: { rule_code: string; applicable: boolean; findings: number; error: string | null }[]
  findings: { rule_code: string; severity: string; title: string; section_path: string | null; page: number | null }[]
}

interface RuleSetDetail extends RuleSetItemOut {
  diff: { against: string | null; added: string[]; removed: string[]; changed: { rule_code: string; fields: string[] }[] }
}

function RuleSetsTab() {
  const { can } = useAuth()
  const [sets, setSets] = useState<RuleSetItemOut[] | null>(null)
  const [selected, setSelected] = useState<RuleSetDetail | null>(null)
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .get<RuleSetItemOut[]>('/rule-sets')
      .then((x) => {
        setSets(x)
        const pick = x.find((s) => s.status === 'draft') ?? x.find((s) => s.status === 'published')
        if (pick) api.get<RuleSetDetail>(`/rule-sets/${pick.id}`).then(setSelected)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [])
  useEffect(load, [load])

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setError(null)
    setNotice(null)
    try {
      await fn()
      setNotice(msg)
      load()
    } catch (e) {
      setError(problems(e))
    }
  }

  if (!sets) return <Spinner />
  const hasDraft = sets.some((s) => s.status === 'draft')
  return (
    <div className="stack">
      {error && <Alert title="Tidak dapat diproses">{error}</Alert>}
      {notice && <Alert tone="ok">{notice}</Alert>}
      {can('rule.manage') && !hasDraft && (
        <Card title="Buat versi baru" sub="Draft berisi snapshot semua aturan aktif saat ini. Uji dengan berkas contoh sebelum diterbitkan.">
          <div className="toolbar" style={{ padding: 0, border: 'none' }}>
            <input className="grow" placeholder="Catatan perubahan (wajib)" value={notes} onChange={(e) => setNotes(e.target.value)} />
            <button
              className="primary"
              disabled={notes.trim().length < 5}
              onClick={() => void act(() => api.post('/rule-sets', { change_notes: notes }), 'Draft rule set dibuat. Jalankan simulasi lalu terbitkan.')}
            >
              <Icon name="plus" size="sm" />
              Buat draft
            </button>
          </div>
        </Card>
      )}
      <div className="grid split">
        <div className="stack">{selected && <RuleSetPanel rs={selected} onAction={act} />}</div>
        <Card title="Riwayat versi" flush>
          <ul className="feed">
            {sets.map((s) => (
              <li key={s.id} style={{ cursor: 'pointer' }} onClick={() => api.get<RuleSetDetail>(`/rule-sets/${s.id}`).then(setSelected)}>
                <span className="feed-icon">
                  <Icon name={s.status === 'published' ? 'checkCircle' : s.status === 'draft' ? 'edit' : 'clock'} />
                </span>
                <div className="feed-text">
                  <div className="row between">
                    <span className="strong">
                      {s.name} v{s.version}
                    </span>
                    <Pill tone={s.status === 'published' ? 'ok' : s.status === 'draft' ? 'info' : 'neutral'}>
                      {s.status === 'published' ? 'Berlaku' : s.status === 'draft' ? 'Draft' : 'Arsip'}
                    </Pill>
                  </div>
                  <div className="xs muted">
                    {s.items_count} aturan · {s.published_at ? `terbit ${fmtDate(s.published_at)}` : `dibuat ${fmtDate(s.created_at)}`}
                  </div>
                  {s.change_notes && <div className="xs ink-2">{s.change_notes}</div>}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}

function RuleSetPanel({ rs, onAction }: { rs: RuleSetDetail; onAction: (fn: () => Promise<unknown>, msg: string) => Promise<void> }) {
  const { can } = useAuth()
  const fileRef = useRef<HTMLInputElement>(null)
  const [options, setOptions] = useState<Options | null>(null)
  const [type, setType] = useState('fiksi')
  const [sim, setSim] = useState<SimResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api
      .get<Options>('/manuscripts/options')
      .then(setOptions)
      .catch(() => undefined)
  }, [])
  const draft = rs.status === 'draft' && can('rule.manage')
  const runs = rs.test_results_json?.runs ?? []

  const simulate = async (file: File) => {
    setBusy(true)
    setError(null)
    const form = new FormData()
    form.append('file', file)
    form.append('manuscript_type', type)
    try {
      setSim(await api.postForm<SimResult>(`/rule-sets/${rs.id}/simulate`, form))
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <>
      <Card
        title={`${rs.name} v${rs.version}`}
        sub={rs.change_notes ?? undefined}
        action={
          draft && (
            <div className="row">
              <button className="sm" onClick={() => void onAction(() => api.delete(`/rule-sets/${rs.id}`), 'Draft dihapus.')}>
                Hapus draft
              </button>
              <button
                className="primary sm"
                onClick={() => void onAction(() => api.post(`/rule-sets/${rs.id}/publish`), `Rule set v${rs.version} diterbitkan.`)}
              >
                <Icon name="check" size="sm" />
                Terbitkan
              </button>
            </div>
          )
        }
      >
        <div className="stack">
          <div>
            <h3 className="mb">Perubahan {rs.diff.against ? `dibanding ${rs.diff.against}` : ''}</h3>
            {!rs.diff.against ? (
              <p className="small muted">Versi pertama.</p>
            ) : !rs.diff.added.length && !rs.diff.removed.length && !rs.diff.changed.length ? (
              <p className="small muted">Tidak ada perubahan aturan.</p>
            ) : (
              <ul className="small" style={{ margin: 0, paddingLeft: '1.1rem' }}>
                {rs.diff.added.map((c) => (
                  <li key={c}>
                    <span className="mono">{c}</span> ditambahkan
                  </li>
                ))}
                {rs.diff.removed.map((c) => (
                  <li key={c}>
                    <span className="mono">{c}</span> dinonaktifkan
                  </li>
                ))}
                {rs.diff.changed.map((c) => (
                  <li key={c.rule_code}>
                    <span className="mono">{c.rule_code}</span> berubah: {c.fields.join(', ')}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {draft && (
            <div>
              <h3 className="mb">Simulasi pada berkas contoh</h3>
              <p className="small muted mb">Berkas tidak disimpan sebagai naskah. Wajib minimal satu simulasi tanpa aturan gagal sebelum terbit.</p>
              <div className="toolbar" style={{ padding: 0, border: 'none' }}>
                <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Jenis naskah uji">
                  {options?.manuscript_types.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
                <input ref={fileRef} type="file" accept=".docx,.pdf,.txt" hidden onChange={(e) => e.target.files?.[0] && void simulate(e.target.files[0])} />
                <button onClick={() => fileRef.current?.click()} disabled={busy}>
                  <Icon name="upload" size="sm" />
                  {busy ? 'Menjalankan…' : 'Pilih berkas uji'}
                </button>
              </div>
              {error && <Alert>{error}</Alert>}
            </div>
          )}
          {sim && <SimulationView sim={sim} />}
          {runs.length > 0 && (
            <div>
              <h3 className="mb">Catatan pengujian ({runs.length})</h3>
              <table className="table bordered">
                <thead>
                  <tr>
                    <th>Berkas</th>
                    <th>ISBN</th>
                    <th>Editorial</th>
                    <th className="num">Temuan</th>
                    <th>Galat</th>
                  </tr>
                </thead>
                <tbody>
                  {[...runs].reverse().map((r) => (
                    <tr key={r.at}>
                      <td className="small">
                        {r.file}
                        <div className="cell-sub">{fmtDate(r.at)}</div>
                      </td>
                      <td>
                        <IsbnBadge value={r.isbn_status} />
                      </td>
                      <td>
                        <EditorialBadge value={r.editorial_status} /> <span className="num small">{r.total ?? ''}</span>
                      </td>
                      <td className="num">{r.findings}</td>
                      <td className="small">{r.errors.length ? r.errors.join(', ') : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
    </>
  )
}

function SimulationView({ sim }: { sim: SimResult }) {
  const errors = sim.rules.filter((r) => r.error)
  return (
    <div className="stack">
      <div className="sev-strip">
        <span className="strong">{sim.file}</span>
        <IsbnBadge value={sim.isbn_status} />
        {sim.score && <EditorialBadge value={sim.score.editorial_status} />}
        <span className="num strong">{sim.score?.total ?? '—'}</span>
        <span className="muted small">
          {sim.findings_total} temuan · {sim.rubric}
        </span>
      </div>
      {errors.length > 0 && <Alert title="Aturan gagal dijalankan">{errors.map((e) => `${e.rule_code}: ${e.error}`).join(' · ')}</Alert>}
      <table className="table bordered">
        <thead>
          <tr>
            <th>Temuan (maks. 300)</th>
            <th>Lokasi</th>
          </tr>
        </thead>
        <tbody>
          {sim.findings.slice(0, 40).map((f, i) => (
            <tr key={i}>
              <td>
                <SeverityBadge value={f.severity} /> <span className="mono xs">{f.rule_code}</span> {f.title}
              </td>
              <td className="small muted">
                {f.section_path ?? 'Seluruh naskah'}
                {f.page ? ` · ± hal. ${f.page}` : ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <details className="chart-table">
        <summary>Checklist ISBN simulasi</summary>
        <table className="table bordered">
          <tbody>
            {sim.compliance.map((c) => (
              <tr key={c.rule_code}>
                <td className="small">
                  <span className="mono xs">{c.rule_code}</span> {c.title}
                </td>
                <td>
                  <ComplianceBadge value={c.result_status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Rubrik
// ---------------------------------------------------------------------------

function RubricsTab() {
  const { can } = useAuth()
  const [options, setOptions] = useState<Options | null>(null)
  const [type, setType] = useState('fiksi')
  const [rubrics, setRubrics] = useState<RubricItem[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    api
      .get<Options>('/manuscripts/options')
      .then(setOptions)
      .catch(() => undefined)
  }, [])
  const load = useCallback(() => {
    api
      .get<RubricItem[]>('/rubrics', { manuscript_type: type })
      .then((x) => {
        setRubrics(x)
        setSelectedId((cur) => (cur && x.some((r) => r.id === cur) ? cur : ((x.find((r) => r.status === 'draft') ?? x[0])?.id ?? null)))
      })
      .catch((e) => setError(errorMessage(e)))
  }, [type])
  useEffect(load, [load])

  const selected = rubrics?.find((r) => r.id === selectedId) ?? null
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setError(null)
    setNotice(null)
    try {
      await fn()
      setNotice(msg)
      load()
    } catch (e) {
      setError(problems(e))
    }
  }

  return (
    <div className="stack">
      <div className="row">
        <span className="strong small">Jenis naskah</span>
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Jenis naskah">
          {options?.manuscript_types.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        {rubrics?.map((r) => (
          <button key={r.id} className={`sm ${r.id === selectedId ? 'primary' : ''}`} onClick={() => setSelectedId(r.id)}>
            v{r.version} · {r.status === 'published' ? 'berlaku' : r.status === 'draft' ? 'draft' : 'arsip'}
          </button>
        ))}
      </div>
      {error && <Alert title="Tidak dapat diproses">{error}</Alert>}
      {notice && <Alert tone="ok">{notice}</Alert>}
      {!rubrics ? (
        <Spinner />
      ) : !selected ? (
        <Empty title="Belum ada rubrik untuk jenis ini" />
      ) : (
        <RubricEditor key={selected.id} r={selected} editable={can('rule.manage')} onAction={act} />
      )}
    </div>
  )
}

function RubricEditor({ r, editable, onAction }: { r: RubricItem; editable: boolean; onAction: (fn: () => Promise<unknown>, msg: string) => Promise<void> }) {
  const draft = r.status === 'draft' && editable
  const [weights, setWeights] = useState<Record<string, string>>(() =>
    Object.fromEntries(r.criteria.map((c) => [c.criterion_code, String(Number(c.weight_percent))])),
  )
  const [th, setTh] = useState({
    pass: String(r.score_thresholds_json.pass ?? 85),
    minor_revision: String(r.score_thresholds_json.minor_revision ?? 70),
    major_revision: String(r.score_thresholds_json.major_revision ?? 55),
    coverage: String(Number(r.min_scoring_coverage)),
  })
  const total = useMemo(() => Object.values(weights).reduce((s, w) => s + (Number(w) || 0), 0), [weights])

  const save = () =>
    onAction(
      () =>
        api.patch(`/rubrics/${r.id}`, {
          criteria: r.criteria.map((c) => ({ criterion_code: c.criterion_code, weight_percent: Number(weights[c.criterion_code]) || 0 })),
          score_thresholds_json: { pass: Number(th.pass), minor_revision: Number(th.minor_revision), major_revision: Number(th.major_revision) },
          min_scoring_coverage: Number(th.coverage),
        }),
      'Draft rubrik disimpan.',
    )

  return (
    <Card
      title={`${r.name} v${r.version}`}
      sub={r.change_notes ?? undefined}
      action={
        editable && (
          <div className="row">
            {r.status === 'published' && (
              <button className="sm" onClick={() => void onAction(() => api.post(`/rubrics/${r.id}/new-version`), 'Draft rubrik baru dibuat dari versi ini.')}>
                <Icon name="plus" size="sm" />
                Buat versi baru
              </button>
            )}
            {draft && (
              <>
                <button className="sm" onClick={() => void onAction(() => api.delete(`/rubrics/${r.id}`), 'Draft dihapus.')}>
                  Hapus draft
                </button>
                <button className="sm" onClick={() => void save()}>
                  Simpan
                </button>
                <button
                  className="primary sm"
                  disabled={Math.abs(total - 100) > 0.01}
                  onClick={() => void onAction(() => api.post(`/rubrics/${r.id}/publish`), `Rubrik v${r.version} diterbitkan.`)}
                >
                  Terbitkan
                </button>
              </>
            )}
          </div>
        )
      }
      flush
    >
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Kriteria</th>
              <th className="num" style={{ width: 140 }}>
                Bobot (%)
              </th>
            </tr>
          </thead>
          <tbody>
            {r.criteria.map((c) => (
              <tr key={c.id}>
                <td>
                  <div className="cell-title">{c.name}</div>
                  <div className="cell-sub">{c.description}</div>
                </td>
                <td className="num">
                  {draft ? (
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      style={{ width: 90, textAlign: 'right' }}
                      value={weights[c.criterion_code]}
                      onChange={(e) => setWeights({ ...weights, [c.criterion_code]: e.target.value })}
                      aria-label={`Bobot ${c.name}`}
                    />
                  ) : (
                    `${Number(c.weight_percent)}%`
                  )}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td className="strong">Total bobot</td>
              <td className="num strong" style={{ color: Math.abs(total - 100) > 0.01 ? 'var(--bad-text)' : undefined }}>
                {total}%{Math.abs(total - 100) > 0.01 && ' (harus 100)'}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <div className="card-body">
        <div className="grid kpis">
          {(
            [
              ['pass', 'Ambang lanjut'],
              ['minor_revision', 'Ambang revisi ringan'],
              ['major_revision', 'Ambang revisi besar'],
              ['coverage', 'Cakupan minimum (%)'],
            ] as const
          ).map(([k, label]) => (
            <label key={k} className="field">
              <span>{label}</span>
              {draft ? <input type="number" min={0} max={100} value={th[k]} onChange={(e) => setTh({ ...th, [k]: e.target.value })} /> : <Tag>{th[k]}</Tag>}
            </label>
          ))}
        </div>
        {r.score_thresholds_json.note && <p className="small muted mt">{r.score_thresholds_json.note}</p>}
      </div>
    </Card>
  )
}
