import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { Icon } from '../components/icons'
import TwoStage from '../components/TwoStage'
import StructureViewer from '../components/StructureViewer'
import { VersionDetail } from '../components/VersionsPanel'
import { Alert, Card, ExtractionBadge, Kpi, PageHeader } from '../components/ui'
import { QUALITY_REASON_LABELS, fmtBytes } from '../labels'
import type { Chapter, ExtractionSummary, Options, Version } from '../types'

interface QuickCheck {
  manuscript_id: string
  internal_code: string
  working_title: string
  version: Version
}

const ACCEPT = '.docx,.pdf,.txt'
const BUSY = new Set(['PENDING', 'PROCESSING'])

export default function QuickCheckPage() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [options, setOptions] = useState<Options | null>(null)
  const [type, setType] = useState('lainnya')
  const [distribution, setDistribution] = useState('')
  const [title, setTitle] = useState('')
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [check, setCheck] = useState<QuickCheck | null>(null)
  const [version, setVersion] = useState<Version | null>(null)

  useEffect(() => {
    api
      .get<Options>('/manuscripts/options')
      .then(setOptions)
      .catch(() => undefined)
  }, [])

  // Ekstraksi berjalan di latar belakang; tanyakan status tiap detik sampai selesai.
  const versionId = check?.version.id
  const done = version && !BUSY.has(version.extraction_status)
  useEffect(() => {
    if (!versionId || done) return
    const t = setInterval(() => {
      api
        .get<Version>(`/versions/${versionId}`)
        .then(setVersion)
        .catch((e) => setError(errorMessage(e)))
    }, 1000)
    return () => clearInterval(t)
  }, [versionId, done])

  const send = async (file: File) => {
    setError(null)
    setCheck(null)
    setVersion(null)
    setUploading(file.name)
    const form = new FormData()
    form.append('file', file)
    form.append('manuscript_type', type)
    if (distribution) form.append('distribution', distribution)
    if (title.trim()) form.append('working_title', title.trim())
    try {
      const res = await api.postForm<QuickCheck>('/quick-checks', form)
      setCheck(res)
      setVersion(res.version)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setUploading(null)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) void send(f)
  }

  const reset = () => {
    setCheck(null)
    setVersion(null)
    setError(null)
    setTitle('')
  }

  if (check && version) return <Result check={check} version={version} onAgain={reset} />

  return (
    <div className="container narrow">
      <PageHeader
        title="Cek Naskah"
        sub="Unggah berkas naskah. Sistem membaca struktur, memeriksa kelengkapan ISBN, menghitung skor editorial, dan menyusun daftar revisi."
      />

      <div className="card dist-picker">
        <div>
          <div className="strong">Rencana peredaran buku</div>
          <div className="xs muted">ISBN hanya untuk terbitan yang diedarkan ke masyarakat umum (Perpusnas 11/2025 Pasal 2; Juknis 4.5).</div>
        </div>
        <select value={distribution} onChange={(e) => setDistribution(e.target.value)} aria-label="Rencana peredaran buku">
          <option value="">Belum ditentukan</option>
          {options?.distribution_options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div
        className={`dropzone ${dragging ? 'over' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => !uploading && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
        aria-label="Pilih atau seret berkas naskah"
        aria-busy={!!uploading}
      >
        <input ref={inputRef} type="file" accept={ACCEPT} hidden onChange={(e) => e.target.files?.[0] && void send(e.target.files[0])} />
        <span className="dropzone-icon">
          <Icon name="upload" size="lg" />
        </span>
        {uploading ? (
          <>
            <span className="dropzone-title">Mengunggah {uploading}…</span>
            <div className="progress">
              <span />
            </div>
          </>
        ) : (
          <>
            <span className="dropzone-title">Seret berkas ke sini, atau klik untuk memilih</span>
            <span className="muted small">DOCX atau PDF berbasis teks · maksimal 50 MB</span>
          </>
        )}
      </div>
      {error && (
        <div className="mt">
          <Alert title="Berkas tidak dapat diproses">{error}</Alert>
        </div>
      )}

      <div className="steps">
        <Step n={1} title="Unggah berkas" text="Berkas asli disimpan utuh dengan checksum; tidak pernah ditimpa." />
        <Step n={2} title="Sistem memeriksa" text="Struktur, kelengkapan ISBN, bahasa, pengulangan, dan rujukan diperiksa dengan aturan berversi." />
        <Step n={3} title="Lihat hasil" text="Status ISBN, skor editorial, dan daftar revisi lengkap dengan lokasi tampil di halaman ini." />
      </div>

      <details className="optional">
        <summary>
          <Icon name="chevronDown" size="sm" />
          Info tambahan (opsional)
        </summary>
        <Card>
          <div className="grid2">
            <label className="field">
              <span>Judul kerja</span>
              <input placeholder="Default: nama berkas" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={1000} />
            </label>
            <label className="field">
              <span>Jenis naskah</span>
              <select value={type} onChange={(e) => setType(e.target.value)}>
                {options?.manuscript_types.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="muted small mt">Penulis dan tanggal masuk dapat dilengkapi nanti di halaman detail naskah.</p>
        </Card>
      </details>
    </div>
  )
}

function Step({ n, title, text }: { n: number; title: string; text: string }) {
  return (
    <div className="step">
      <span className="step-n">{n}</span>
      <div>
        <div className="strong" style={{ color: 'var(--ink)' }}>
          {title}
        </div>
        {text}
      </div>
    </div>
  )
}

const PAGE_SOURCE: Record<string, string> = {
  pdf: 'Halaman fisik PDF',
  word_app_properties: 'Menurut Word saat terakhir disimpan',
  page_breaks: 'Perkiraan dari pemisah halaman',
}

function Result({ check, version, onAgain }: { check: QuickCheck; version: Version; onAgain: () => void }) {
  const s = version.extraction_summary_json
  const busy = BUSY.has(version.extraction_status)
  const counts = s.block_counts ?? {}
  const failed = version.extraction_status === 'FAILED'

  return (
    <div className="container stack">
      <PageHeader
        eyebrow={
          <>
            <span className="mono">{check.internal_code}</span> · Hasil pemeriksaan naskah
          </>
        }
        title={check.working_title}
        sub={
          <span className="row">
            <ExtractionBadge status={version.extraction_status} />
            <span className="muted small">
              {version.original_filename} · {fmtBytes(version.file_size_bytes)}
            </span>
          </span>
        }
        actions={
          <>
            <Link className="button" to={`/naskah/${check.manuscript_id}`}>
              Detail naskah
            </Link>
            <button className="primary" onClick={onAgain}>
              <Icon name="upload" size="sm" />
              Cek naskah lain
            </button>
          </>
        }
      />

      {busy && (
        <Card>
          <div className="empty">
            <div className="progress">
              <span />
            </div>
            <strong>Sedang membaca naskah…</strong>
            <span className="small">Hasil muncul otomatis. Naskah panjang bisa memerlukan beberapa detik.</span>
          </div>
        </Card>
      )}

      {failed && (
        <Alert title="Berkas tidak dapat dibaca">{s.error?.message ?? 'Terjadi kesalahan saat membaca berkas.'} Periksa berkas, lalu unggah ulang.</Alert>
      )}

      {!busy && !failed && (
        <>
          <TwoStage versionId={version.id} ready={!busy && !failed} />
          <h2 className="mt">Struktur naskah</h2>
          {version.extraction_status === 'INCOMPLETE' && (
            <Alert tone="warn" title="Naskah hanya terbaca sebagian">
              {s.quality?.reasons.map((r) => QUALITY_REASON_LABELS[r] ?? r).join('; ')}. Bila berkas hasil pindai (scan), unggah versi DOCX atau PDF yang
              teksnya dapat diseleksi.
            </Alert>
          )}
          <div className="grid kpis">
            <Kpi label="Bab" value={s.chapters?.length ?? 0} icon="layers" tone="brand" foot={`${counts.heading ?? 0} judul termasuk bagian awal/akhir`} />
            <Kpi label="Halaman" value={s.page_count ?? '—'} icon="file" foot={PAGE_SOURCE[s.page_count_source ?? ''] ?? 'Tidak tersedia'} />
            <Kpi
              label="Kata"
              value={(s.word_count ?? 0).toLocaleString('id-ID')}
              icon="hash"
              foot={`${(s.char_count ?? 0).toLocaleString('id-ID')} karakter`}
            />
            <Kpi
              label="Kualitas baca"
              value={s.quality ? Math.round(s.quality.score) : '—'}
              unit="/100"
              icon="activity"
              tone={s.quality && s.quality.score >= 60 ? 'ok' : 'warn'}
              foot="Keterbacaan teks, bukan mutu isi"
            />
            <Kpi label="Tabel & catatan kaki" value={`${counts.table ?? 0} · ${counts.footnote ?? 0}`} icon="grid" foot="tabel · catatan kaki" />
          </div>
          <Chapters summary={s} />
          <details className="optional">
            <summary>
              <Icon name="chevronDown" size="sm" />
              Baca isi naskah per bagian
            </summary>
            <StructureViewer versions={[version]} />
          </details>
          <details className="optional">
            <summary>
              <Icon name="chevronDown" size="sm" />
              Rincian teknis pembacaan
            </summary>
            <VersionDetail v={version} canReextract={false} onReextract={() => undefined} />
          </details>
        </>
      )}
    </div>
  )
}

function tocPage(s: ExtractionSummary, c: Chapter): string | null {
  const re = new RegExp(`^BAB\\s+${c.label}\\b`, 'i')
  return s.toc_entries?.find((t) => re.test(t.title))?.page_label ?? null
}

function Chapters({ summary: s }: { summary: ExtractionSummary }) {
  const chapters = s.chapters ?? []
  if (!chapters.length) {
    return (
      <Alert tone="warn" title='Tidak ada judul berpola "BAB n" yang terdeteksi'>
        Pastikan judul bab memakai style Heading 1 (DOCX) atau bookmark (PDF), dan diawali kata "BAB".
      </Alert>
    )
  }
  const exact = s.page_numbers_reliable
  const hasToc = !!s.toc_entries?.length
  const pages = s.page_count ?? null
  return (
    <Card
      title={`Daftar bab (${chapters.length})`}
      sub={exact ? 'Halaman fisik PDF' : 'Halaman DOCX dari tata letak terakhir Word; dapat bergeser bila dibuka dengan ukuran kertas/font berbeda.'}
      flush
    >
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 90 }}>Bab</th>
              <th>Judul</th>
              <th className="num">Mulai hal.</th>
              <th className="num">Panjang</th>
              {hasToc && <th className="num">Di daftar isi</th>}
            </tr>
          </thead>
          <tbody>
            {chapters.map((c, i) => {
              const page = exact ? c.page_number : c.page_estimate
              const next = chapters[i + 1]
              const nextPage = next ? (exact ? next.page_number : next.page_estimate) : pages ? pages + 1 : null
              const length = page && nextPage ? nextPage - page : null
              const toc = tocPage(s, c)
              const mismatch = toc && page && String(page) !== toc
              return (
                <tr key={c.block_id}>
                  <td className="nowrap strong">BAB {c.label}</td>
                  <td>{c.title ?? <span className="muted">(tanpa judul)</span>}</td>
                  <td className="num">{page ?? '—'}</td>
                  <td className="num muted">{length !== null && length > 0 ? `${length} hal.` : '—'}</td>
                  {hasToc && (
                    <td className="num">
                      {toc ? (
                        <span className="row" style={{ justifyContent: 'flex-end' }}>
                          {toc}
                          {mismatch ? (
                            <span title="Berbeda dengan halaman hasil baca" style={{ color: 'var(--warn-text)' }}>
                              <Icon name="alert" size="sm" />
                            </span>
                          ) : (
                            <span title="Sama dengan halaman hasil baca" style={{ color: 'var(--ok-text)' }}>
                              <Icon name="check" size="sm" />
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="muted">tidak tercantum</span>
                      )}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
