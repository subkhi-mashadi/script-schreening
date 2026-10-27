import { useRef, useState } from 'react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { BLOCK_LABELS, QUALITY_REASON_LABELS, fmtBytes, fmtDate } from '../labels'
import type { Manuscript, Version } from '../types'
import { Icon } from './icons'
import { Alert, Card, Empty, ExtractionBadge, Pill } from './ui'

const ACCEPT = '.docx,.pdf,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain'

export default function VersionsPanel({ manuscript, onChanged }: { manuscript: Manuscript; onChanged: () => void }) {
  const { can } = useAuth()
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [detail, setDetail] = useState<Version | null>(null)

  const submit = async (file: File) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const v = await api.upload<Version>(`/manuscripts/${manuscript.id}/versions`, file, crypto.randomUUID())
      const dup = v.warnings.find((w) => w.startsWith('DUPLICATE_OF_VERSION_'))
      setNotice(
        `Versi ${v.version_number} tersimpan. Pembacaan berjalan di latar belakang.` +
          (dup ? ` Perhatian: isi berkas identik dengan versi ${dup.split('_').pop()}.` : ''),
      )
      onChanged()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const showDetail = async (id: string) => {
    if (detail?.id === id) return setDetail(null)
    try {
      setDetail(await api.get<Version>(`/versions/${id}`))
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const reextract = async (id: string) => {
    try {
      await api.post(`/versions/${id}/extract`)
      setDetail(null)
      onChanged()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <div className="stack">
      {error && <Alert>{error}</Alert>}
      {notice && <Alert tone="ok">{notice}</Alert>}
      <Card
        title="Riwayat versi berkas"
        sub="Setiap unggahan menjadi versi baru; berkas lama tidak pernah ditimpa."
        action={
          can('version.upload') && (
            <>
              <input ref={fileRef} type="file" accept={ACCEPT} hidden onChange={(e) => e.target.files?.[0] && void submit(e.target.files[0])} />
              <button className="primary sm" onClick={() => fileRef.current?.click()} disabled={busy}>
                <Icon name="upload" size="sm" />
                {busy ? 'Mengunggah…' : 'Unggah versi baru'}
              </button>
            </>
          )
        }
        flush
      >
        {manuscript.versions.length === 0 ? (
          <Empty icon="upload" title="Belum ada berkas yang diunggah" />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Versi</th>
                  <th>Berkas</th>
                  <th>Status</th>
                  <th className="num">Kualitas</th>
                  <th>SHA-256</th>
                  <th>Diunggah</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {[...manuscript.versions].reverse().map((v, i) => (
                  <tr key={v.id}>
                    <td className="nowrap">
                      <span className="strong">v{v.version_number}</span> {i === 0 && <Pill tone="info">Terbaru</Pill>}
                    </td>
                    <td>
                      <div className="cell-title truncate" style={{ maxWidth: 320 }}>
                        {v.original_filename}
                      </div>
                      <div className="cell-sub">
                        {v.source_format.toUpperCase()} · {fmtBytes(v.file_size_bytes)}
                      </div>
                    </td>
                    <td>
                      <ExtractionBadge status={v.extraction_status} />
                    </td>
                    <td className="num">{v.extraction_quality !== null ? Number(v.extraction_quality).toFixed(0) : '—'}</td>
                    <td className="mono xs muted" title={v.sha256_checksum}>
                      {v.sha256_checksum.slice(0, 10)}…
                    </td>
                    <td className="nowrap small ink-2">{fmtDate(v.uploaded_at)}</td>
                    <td className="nowrap">
                      <button className="link" onClick={() => void showDetail(v.id)}>
                        {detail?.id === v.id ? 'Tutup' : 'Rincian'}
                      </button>
                      {can('version.download') && (
                        <button
                          className="link"
                          onClick={() => void api.download(`/versions/${v.id}/download`, v.original_filename).catch((e) => setError(errorMessage(e)))}
                        >
                          Unduh
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {detail && <VersionDetail v={detail} canReextract={can('version.reextract')} onReextract={() => void reextract(detail.id)} />}
    </div>
  )
}

const SEVERITY: Record<string, { tone: 'bad' | 'warn' | 'info'; label: string }> = {
  error: { tone: 'bad', label: 'Galat' },
  warning: { tone: 'warn', label: 'Peringatan' },
  info: { tone: 'info', label: 'Info' },
}

export function VersionDetail({ v, canReextract, onReextract }: { v: Version; canReextract: boolean; onReextract: () => void }) {
  const s = v.extraction_summary_json
  return (
    <Card
      title={`Rincian pembacaan versi ${v.version_number}`}
      action={
        canReextract &&
        v.extraction_status !== 'PROCESSING' && (
          <button className="sm" onClick={onReextract}>
            <Icon name="refresh" size="sm" />
            Proses ulang
          </button>
        )
      }
    >
      <div className="stack">
        {s.error && (
          <Alert title={s.error.code}>
            {s.error.message}
            {s.error.kind === 'document'
              ? ' Perbaiki berkas lalu unggah ulang sebagai versi baru.'
              : ' Coba proses ulang; bila berulang, hubungi admin sistem.'}
          </Alert>
        )}
        {v.extraction_status === 'INCOMPLETE' && (
          <Alert tone="warn" title="Pembacaan tidak lengkap">
            Hasil pemeriksaan untuk versi ini tidak boleh dianggap final. {s.quality?.reasons.map((r) => QUALITY_REASON_LABELS[r] ?? r).join('; ')}
          </Alert>
        )}
        <dl className="facts">
          <dt>Status</dt>
          <dd>
            <ExtractionBadge status={v.extraction_status} />
          </dd>
          <dt>Kualitas baca</dt>
          <dd>{s.quality ? `${s.quality.score}/100 — keterbacaan teks, bukan mutu naskah` : '—'}</dd>
          <dt>Ukuran isi</dt>
          <dd className="num">
            {(s.char_count ?? 0).toLocaleString('id-ID')} karakter · {(s.word_count ?? 0).toLocaleString('id-ID')} kata · {s.block_count ?? 0} blok
            {s.page_count ? ` · ${s.page_count} halaman` : ''}
          </dd>
          <dt>Komposisi blok</dt>
          <dd>
            {Object.entries(s.block_counts ?? {})
              .map(([k, n]) => `${BLOCK_LABELS[k] ?? k} ${n}`)
              .join(' · ') || '—'}
          </dd>
          <dt>Nomor halaman</dt>
          <dd>{s.page_numbers_reliable ? 'Tersedia (halaman fisik PDF)' : 'Perkiraan dari tata letak Word — lokasi utama memakai bab/paragraf'}</dd>
          <dt>Mesin pembaca</dt>
          <dd className="mono xs">{v.extraction_engine_version ?? '—'}</dd>
          <dt>SHA-256</dt>
          <dd className="mono xs" style={{ wordBreak: 'break-all' }}>
            {v.sha256_checksum}
          </dd>
          <dt>Diunggah oleh</dt>
          <dd>
            {v.uploader?.full_name} · {fmtDate(v.uploaded_at)}
          </dd>
        </dl>
        {!!s.warnings?.length && (
          <div>
            <h3 className="mb">Catatan pembacaan</h3>
            <ul className="warnings">
              {s.warnings.map((w, i) => (
                <li key={i} className="row" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
                  <Pill tone={SEVERITY[w.severity]?.tone}>{SEVERITY[w.severity]?.label ?? w.severity}</Pill>
                  <span className="ink-2">{w.message}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  )
}
