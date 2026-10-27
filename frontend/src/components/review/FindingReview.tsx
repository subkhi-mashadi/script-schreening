import { useState } from 'react'
import { api, errorMessage } from '../../api'
import { fmtDate } from '../../labels'
import type { FindingItem } from '../../types'
import { Icon } from '../icons'
import { VerifyBadge } from '../status'

export type ReviewAction = 'confirm' | 'false_positive' | 'needs_check' | 'reset'

async function sendReview(runId: string, ids: string[], action: ReviewAction, note?: string) {
  return api.post(`/screenings/${runId}/findings/review`, { finding_ids: ids, action, note: note || null })
}

/** Kontrol verifikasi satu temuan. Editor menilai temuan, bukan skor; skor dihitung ulang sistem. */
export function FindingReview({ runId, f, editable, onDone }: { runId: string; f: FindingItem; editable: boolean; onDone: () => void }) {
  const [mode, setMode] = useState<ReviewAction | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (action: ReviewAction, n?: string) => {
    setBusy(true)
    setError(null)
    try {
      await sendReview(runId, [f.id], action, n)
      setMode(null)
      setNote('')
      onDone()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const locked = f.verification_status === 'RESOLVED_IN_NEW_VERSION'
  return (
    <div className="review">
      <div className="row" style={{ gap: '0.4rem' }}>
        <VerifyBadge value={f.verification_status} />
        {f.reviewed_at && <span className="xs muted">{fmtDate(f.reviewed_at)}</span>}
        {editable && !locked && (
          <span className="review-actions">
            <button
              className="sm ghost"
              disabled={busy || f.verification_status === 'CONFIRMED'}
              onClick={() => void submit('confirm')}
              title="Temuan benar; perlu direvisi"
            >
              <Icon name="check" size="sm" />
              Benar
            </button>
            <button
              className="sm ghost"
              disabled={busy}
              onClick={() => setMode(mode === 'false_positive' ? null : 'false_positive')}
              title="Mesin keliru mendeteksi"
            >
              <Icon name="xCircle" size="sm" />
              Salah deteksi
            </button>
            <button className="sm ghost" disabled={busy} onClick={() => setMode(mode === 'needs_check' ? null : 'needs_check')}>
              <Icon name="search" size="sm" />
              Cek lanjutan
            </button>
            {f.verification_status !== 'UNREVIEWED' && (
              <button className="sm ghost" disabled={busy} onClick={() => void submit('reset')}>
                Batalkan
              </button>
            )}
          </span>
        )}
      </div>
      {f.review_note && <p className="xs ink-2 review-note">Catatan editor: {f.review_note}</p>}
      {mode && (
        <div className="row review-form">
          <input
            className="grow"
            autoFocus
            placeholder={mode === 'false_positive' ? 'Alasan mesin keliru (wajib)' : 'Apa yang perlu dicek? (opsional)'}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && note.trim() && void submit(mode, note)}
          />
          <button className="sm primary" disabled={busy || (mode === 'false_positive' && !note.trim())} onClick={() => void submit(mode, note)}>
            Simpan
          </button>
        </div>
      )}
      {error && (
        <p className="xs" style={{ color: 'var(--bad-text)' }}>
          {error}
        </p>
      )}
    </div>
  )
}

/** Bilah aksi massal untuk temuan terpilih. */
export function BulkBar({ runId, ids, onDone, onClear }: { runId: string; ids: string[]; onDone: () => void; onClear: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState('')
  if (!ids.length) return null
  const go = async (action: ReviewAction) => {
    setBusy(true)
    setError(null)
    try {
      await sendReview(runId, ids, action, note)
      setNote('')
      onClear()
      onDone()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="bulkbar">
      <span className="strong">{ids.length} dipilih</span>
      <input className="grow" placeholder="Catatan (wajib untuk salah deteksi)" value={note} onChange={(e) => setNote(e.target.value)} />
      <button className="sm" disabled={busy} onClick={() => void go('confirm')}>
        Tandai benar
      </button>
      <button className="sm" disabled={busy || !note.trim()} onClick={() => void go('false_positive')}>
        Salah deteksi
      </button>
      <button className="sm" disabled={busy} onClick={() => void go('needs_check')}>
        Cek lanjutan
      </button>
      <button className="sm ghost" onClick={onClear}>
        Batal pilih
      </button>
      {error && (
        <span className="xs" style={{ color: 'var(--bad-text)' }}>
          {error}
        </span>
      )}
    </div>
  )
}
