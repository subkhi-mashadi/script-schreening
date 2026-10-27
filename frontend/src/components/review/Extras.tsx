import { useEffect, useState } from 'react'
import { api, errorMessage, tokenStore } from '../../api'
import { useAuth } from '../../auth'
import { REVIEW_ACTION_LABELS, VERIFY_LABELS, fmtDate } from '../../labels'
import type { ComplianceItem, Comparison, ReviewLogItem, ScreeningRun } from '../../types'
import { Icon } from '../icons'
import { EditorialBadge, IsbnBadge, SeverityBadge } from '../status'
import { Card, Empty, Skeleton } from '../ui'

/** Tombol unduh laporan PDF/HTML/CSV (FR-11). */
export function ReportBar({ run }: { run: ScreeningRun }) {
  const { can } = useAuth()
  const [error, setError] = useState<string | null>(null)
  if (!can('report.export')) return null
  const dl = (path: string, name: string) => api.download(path, name).catch((e) => setError(errorMessage(e)))
  const openHtml = async () => {
    try {
      const token = tokenStore.get()
      const res = await fetch(`/api/v1/screenings/${run.id}/report?format=html`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      if (!res.ok) throw new Error('Laporan gagal dibuat.')
      const url = URL.createObjectURL(new Blob([await res.text()], { type: 'text/html' }))
      window.open(url, '_blank', 'noopener')
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (e) {
      setError(errorMessage(e))
    }
  }
  return (
    <div className="row">
      <button className="sm" onClick={() => void dl(`/screenings/${run.id}/report?format=pdf`, `laporan-screening-${run.run_number}.pdf`)}>
        <Icon name="download" size="sm" />
        Laporan PDF
      </button>
      <button className="sm" onClick={() => void openHtml()}>
        <Icon name="file" size="sm" />
        Versi cetak
      </button>
      <button className="sm" onClick={() => void dl(`/screenings/${run.id}/export?kind=findings`, `temuan-${run.run_number}.csv`)}>
        CSV temuan
      </button>
      <button className="sm" onClick={() => void dl(`/screenings/${run.id}/export?kind=scores`, `skor-${run.run_number}.csv`)}>
        CSV skor
      </button>
      {error && (
        <span className="xs" style={{ color: 'var(--bad-text)' }}>
          {error}
        </span>
      )}
    </div>
  )
}

/** Perbandingan dengan screening versi berkas sebelumnya (FR-10). */
export function ComparisonCard({ run }: { run: ScreeningRun }) {
  const [cmp, setCmp] = useState<Comparison | null | undefined>(undefined)
  const [open, setOpen] = useState<'resolved' | 'new' | 'persisting' | null>(null)
  useEffect(() => {
    api
      .get<Comparison | null>(`/screenings/${run.id}/comparison`)
      .then(setCmp)
      .catch(() => setCmp(null))
  }, [run.id, run.recalculated_at])
  if (cmp === undefined) return <Skeleton height={90} />
  if (cmp === null) return null
  const delta = cmp.current.total_score !== null && cmp.previous.total_score !== null ? cmp.current.total_score - cmp.previous.total_score : null
  const lists = { resolved: cmp.resolved, new: cmp.new, persisting: cmp.persisting }
  const labels = { resolved: 'Sudah diperbaiki', new: 'Temuan baru', persisting: 'Masih ada' }
  return (
    <Card
      title={`Dibanding versi ${cmp.previous.version_number}`}
      sub={
        cmp.rule_set_changed || cmp.rubric_changed
          ? 'Catatan: versi aturan/rubrik berbeda, sebagian perubahan bisa berasal dari aturan.'
          : 'Aturan & rubrik sama.'
      }
    >
      <div className="cmp-grid">
        <div>
          <div className="xs muted">Skor editorial</div>
          <div className="strong num">
            {cmp.previous.total_score ?? '—'} → {cmp.current.total_score ?? '—'}{' '}
            {delta !== null && (
              <span className={delta >= 0 ? 'delta-up' : 'delta-down'}>
                ({delta >= 0 ? '+' : ''}
                {delta.toFixed(1)})
              </span>
            )}
          </div>
          <div className="row" style={{ marginTop: 4 }}>
            <EditorialBadge value={cmp.previous.editorial_status} /> → <EditorialBadge value={cmp.current.editorial_status} />
          </div>
        </div>
        <div>
          <div className="xs muted">ISBN</div>
          <div className="row" style={{ marginTop: 4 }}>
            <IsbnBadge value={cmp.previous.isbn_status} /> → <IsbnBadge value={cmp.current.isbn_status} />
          </div>
        </div>
        {(['resolved', 'new', 'persisting'] as const).map((k) => (
          <button key={k} className={`cmp-stat ${open === k ? 'active' : ''}`} onClick={() => setOpen(open === k ? null : k)}>
            <span className="kpi-value" style={{ fontSize: '1.5rem' }}>
              {lists[k].length}
            </span>
            <span className="small">{labels[k]}</span>
          </button>
        ))}
      </div>
      {open && (
        <table className="table bordered mt">
          <tbody>
            {lists[open].length === 0 ? (
              <tr>
                <td className="muted">Tidak ada.</td>
              </tr>
            ) : (
              lists[open].map((f) => (
                <tr key={f.id}>
                  <td>
                    <SeverityBadge value={f.severity} /> {f.title}
                  </td>
                  <td className="small muted">{f.section_path ?? 'Seluruh naskah'}</td>
                  <td className="mono xs">{f.rule_code}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
    </Card>
  )
}

/** Jejak verifikasi editor & keputusan. */
export function ReviewLog({ run }: { run: ScreeningRun }) {
  const [items, setItems] = useState<ReviewLogItem[] | null>(null)
  useEffect(() => {
    api
      .get<ReviewLogItem[]>(`/screenings/${run.id}/review-log`)
      .then(setItems)
      .catch(() => setItems([]))
  }, [run.id, run.recalculated_at, run.final_decision])
  if (!items) return <Skeleton height={120} />
  return (
    <Card title="Jejak verifikasi" sub="Setiap tindakan tercatat dan tidak dapat diubah." flush>
      {items.length === 0 ? (
        <Empty icon="user" title="Belum ada verifikasi editor" />
      ) : (
        <ul className="feed">
          {items.map((a) => (
            <li key={a.id}>
              <span className="feed-icon">
                <Icon name={a.action_type === 'decision' ? 'shield' : a.action_type === 'false_positive' ? 'xCircle' : 'check'} />
              </span>
              <div className="feed-text">
                <div>
                  <span className="strong">{a.actor_name ?? 'Sistem'}</span> {REVIEW_ACTION_LABELS[a.action_type] ?? a.action_type}
                  {a.previous_status && a.new_status && a.action_type !== 'decision' && (
                    <span className="xs muted">
                      {' '}
                      ({VERIFY_LABELS[a.previous_status] ?? a.previous_status} → {VERIFY_LABELS[a.new_status] ?? a.new_status})
                    </span>
                  )}
                </div>
                {a.comment && <div className="xs ink-2">{a.comment}</div>}
                <div className="xs muted">{fmtDate(a.created_at)}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/** Pencatatan bukti manual untuk item ISBN yang memerlukan dokumen di luar naskah. */
export function ManualEvidence({ runId, c, editable, onDone }: { runId: string; c: ComplianceItem; editable: boolean; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [observed, setObserved] = useState<'pass' | 'fail'>('pass')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  if (!c.requires_human_verification && c.observed !== 'unknown') return null
  const save = async () => {
    setError(null)
    try {
      await api.post(`/screenings/${runId}/compliance/${c.id}/evidence`, { observed, note })
      setOpen(false)
      setNote('')
      onDone()
    } catch (e) {
      setError(errorMessage(e))
    }
  }
  return (
    <div className="small" style={{ marginTop: 6 }}>
      {c.manual_observed && (
        <div className="xs ink-2">
          Bukti manual: <span className="strong">{c.manual_observed === 'pass' ? 'diterima' : 'tidak ada/tidak sah'}</span> — {c.manual_note}
          {c.verified_at && <span className="muted"> · {fmtDate(c.verified_at)}</span>}
        </div>
      )}
      {editable && !open && (
        <button className="link" onClick={() => setOpen(true)}>
          {c.manual_observed ? 'Ubah bukti manual' : 'Catat bukti manual'}
        </button>
      )}
      {open && (
        <div className="row review-form">
          <select value={observed} onChange={(e) => setObserved(e.target.value as 'pass' | 'fail')} aria-label="Hasil pemeriksaan bukti">
            <option value="pass">Bukti diterima</option>
            <option value="fail">Bukti tidak ada/tidak sah</option>
          </select>
          <input
            className="grow"
            placeholder="Dokumen yang diperiksa (mis. surat pernyataan, tanggal)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button className="sm primary" disabled={note.trim().length < 5} onClick={() => void save()}>
            Simpan
          </button>
          <button className="sm ghost" onClick={() => setOpen(false)}>
            Batal
          </button>
          {error && (
            <span className="xs" style={{ color: 'var(--bad-text)' }}>
              {error}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
