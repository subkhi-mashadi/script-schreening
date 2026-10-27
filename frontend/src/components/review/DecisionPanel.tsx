import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, errorMessage } from '../../api'
import { DECISION_LABELS, fmtDate } from '../../labels'
import type { DecisionInfo, ScreeningRun } from '../../types'
import { Icon } from '../icons'
import { DecisionBadge } from '../status'
import { Alert, Card, Skeleton } from '../ui'

const CHOICES = ['ACCEPTED_FOR_NEXT_STAGE', 'REVISION_REQUIRED', 'REJECTED', 'PENDING_VERIFICATION', 'SCREENING_INCOMPLETE'] as const

export default function DecisionPanel({ run, onChanged }: { run: ScreeningRun; onChanged: () => void }) {
  const [info, setInfo] = useState<DecisionInfo | null>(null)
  const [choice, setChoice] = useState<string>('')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api
      .get<DecisionInfo>(`/screenings/${run.id}/decision`)
      .then((d) => {
        setInfo(d)
        setChoice((c) => c || d.recommendation)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [run.id])
  useEffect(load, [load, run.recalculated_at, run.final_decision])

  if (!info) return <Skeleton height={220} />
  const v = info.verification
  const pct = v.total ? Math.round((v.reviewed / v.total) * 100) : 100
  const needsNote = choice === 'REVISION_REQUIRED' || choice === 'REJECTED'
  const acceptBlocked = choice === 'ACCEPTED_FOR_NEXT_STAGE' && info.accept_blockers.length > 0

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.post(`/screenings/${run.id}/decision`, { decision: choice, note: note || null })
      setNote('')
      load()
      onChanged()
    } catch (e) {
      const problems = e instanceof ApiError ? (e.details as { problems?: string[] } | undefined)?.problems : undefined
      setError(problems?.length ? `${errorMessage(e)} ${problems.join(' · ')}` : errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid split">
      <div className="stack">
        <Card title="Keputusan akhir" sub="Ditetapkan oleh manajer/editor-in-chief setelah membaca hasil sistem dan verifikasi editor.">
          {info.final_decision ? (
            <div className="stack">
              <div className="row">
                <DecisionBadge value={info.final_decision} />
                <span className="small muted">
                  oleh {info.decided_by} · {fmtDate(info.decided_at)}
                </span>
              </div>
              {info.decision_note && <blockquote className="excerpt">{info.decision_note}</blockquote>}
            </div>
          ) : (
            <p className="muted small">Belum ditetapkan.</p>
          )}
          {!info.is_latest && (
            <Alert tone="info" title="Sudah ada screening yang lebih baru">
              Keputusan ditetapkan pada screening terbaru naskah ini.
            </Alert>
          )}
          {info.can_decide && info.is_latest && (
            <div className="stack mt">
              <div className="decision-options" role="radiogroup" aria-label="Pilih keputusan">
                {CHOICES.map((c) => (
                  <label key={c} className={`decision-option ${choice === c ? 'active' : ''}`}>
                    <input type="radio" name="decision" value={c} checked={choice === c} onChange={() => setChoice(c)} />
                    <span>
                      <span className="strong">{DECISION_LABELS[c]}</span>
                      {c === info.recommendation && (
                        <span className="tag" style={{ marginLeft: 6 }}>
                          Rekomendasi sistem
                        </span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
              {acceptBlocked && (
                <Alert tone="warn" title="Belum dapat diteruskan">
                  <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>
                    {info.accept_blockers.map((b) => (
                      <li key={b}>{b}</li>
                    ))}
                  </ul>
                </Alert>
              )}
              <label className="field">
                <span>Catatan keputusan {needsNote ? <span className="hint">wajib, min. 10 karakter</span> : <span className="hint">opsional</span>}</span>
                <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Alasan dan arahan untuk penulis/operator" />
              </label>
              {error && <Alert>{error}</Alert>}
              <div>
                <button className="primary" disabled={busy || acceptBlocked || (needsNote && note.trim().length < 10)} onClick={() => void submit()}>
                  <Icon name="check" size="sm" />
                  Tetapkan keputusan
                </button>
              </div>
            </div>
          )}
        </Card>
      </div>
      <div className="stack">
        <Card title="Kesiapan keputusan">
          <div className="stack">
            <div>
              <div className="row between small">
                <span>Temuan diverifikasi editor</span>
                <span className="num strong">
                  {v.reviewed}/{v.total}
                </span>
              </div>
              <div className="mini-track" style={{ marginTop: 6 }}>
                <div className="mini-fill" style={{ width: `${pct}%` }} />
              </div>
            </div>
            <div className="small">
              <div className="muted">Rekomendasi sistem</div>
              <DecisionBadge value={info.recommendation} />
            </div>
            {info.accept_blockers.length > 0 ? (
              <div className="small">
                <div className="muted">Penghalang untuk diteruskan</div>
                <ul style={{ margin: '0.25rem 0 0', paddingLeft: '1.1rem' }}>
                  {info.accept_blockers.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="small" style={{ color: 'var(--ok-text)' }}>
                Tidak ada penghalang untuk diteruskan.
              </p>
            )}
            <p className="xs muted">{info.note}</p>
          </div>
        </Card>
        {info.history.length > 0 && (
          <Card title="Riwayat keputusan" flush>
            <ul className="feed">
              {info.history.map((h) => (
                <li key={h.id}>
                  <span className="feed-icon">
                    <Icon name="shield" />
                  </span>
                  <div className="feed-text">
                    <div>
                      <span className="strong">{h.actor_name}</span> → {DECISION_LABELS[h.new_status ?? ''] ?? h.new_status}
                    </div>
                    {h.comment && <div className="xs ink-2">{h.comment}</div>}
                    <div className="xs muted">{fmtDate(h.created_at)}</div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </div>
  )
}
