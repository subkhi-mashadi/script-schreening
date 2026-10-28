import { useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { fmtDate } from '../labels'
import type { Classification, ClassItem, ComplianceItem, ScreeningRun } from '../types'
import { useLatestScreening } from '../useScreening'
import { Icon } from './icons'
import { ReportBar } from './review/Extras'
import ScreeningResult from './ScreeningResult'
import { Alert, Card, Pill, Skeleton } from './ui'

const RUNNING = new Set(['QUEUED', 'PROCESSING'])

/** Alur dua tahap: (1) kelayakan ISBN otomatis saat unggah, (2) cek layout atas permintaan. */
export default function TwoStage({ versionId, ready }: { versionId: string; ready: boolean }) {
  const isbn = useLatestScreening(versionId, ready, 'isbn')
  const layout = useLatestScreening(versionId, ready, 'layout', false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { can } = useAuth()

  const startLayout = async () => {
    setStarting(true)
    setError(null)
    try {
      await api.post(`/versions/${versionId}/layout-check`)
      layout.reload()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="stack">
      <div className="stage-head">
        <span className="stage-num">1</span>
        <div>
          <h2>Kelayakan ISBN</h2>
          <p className="small muted">Diperiksa otomatis saat naskah diunggah, berdasarkan Peraturan Perpusnas No. 11 Tahun 2025 dan Juknis Layanan ISBN.</p>
        </div>
      </div>
      {isbn.error && <Alert>{isbn.error}</Alert>}
      {!isbn.run || RUNNING.has(isbn.run.status) ? <Working label="Memeriksa kelayakan ISBN…" /> : <IsbnVerdict run={isbn.run} onRerun={isbn.rerun} />}

      <div className="stage-head mt">
        <span className="stage-num">2</span>
        <div>
          <h2>Cek layout naskah</h2>
          <p className="small muted">Opsional. Memeriksa tata letak (ukuran halaman, margin, huruf, spasi, nomor halaman, gambar) dan kerapian teks.</p>
        </div>
      </div>
      {error && <Alert>{error}</Alert>}
      {!layout.loaded ? (
        <Skeleton height={120} />
      ) : !layout.run ? (
        <Card>
          <div className="cta">
            <span className="dropzone-icon">
              <Icon name="layers" size="lg" />
            </span>
            <div>
              <strong>Belum ada cek layout untuk versi ini</strong>
              <p className="small muted">Jalankan bila naskah akan masuk tahap tata letak/cetak. Hasil berupa skor, ringkasan tata letak, dan daftar revisi.</p>
            </div>
            {can('screening.run') && (
              <button className="primary" disabled={starting || !ready} onClick={() => void startLayout()}>
                <Icon name="layers" size="sm" />
                {starting ? 'Menyiapkan…' : 'Generate cek layout'}
              </button>
            )}
          </div>
        </Card>
      ) : RUNNING.has(layout.run.status) ? (
        <Working label="Memeriksa tata letak dan kerapian naskah…" />
      ) : (
        <>
          <div className="row between">
            <span className="small muted">Dicek {fmtDate(layout.run.completed_at)}</span>
            {can('screening.run') && (
              <button className="sm" onClick={() => void startLayout()} disabled={starting}>
                <Icon name="refresh" size="sm" />
                Cek ulang layout
              </button>
            )}
          </div>
          <ScreeningResult run={layout.run} onRerun={layout.rerun} onChanged={layout.reload} />
        </>
      )}
    </div>
  )
}

function Working({ label }: { label: string }) {
  return (
    <Card>
      <div className="empty">
        <div className="progress">
          <span />
        </div>
        <strong>{label}</strong>
      </div>
    </Card>
  )
}

const FIX: Record<string, string> = {
  'ISB-001': 'Tambahkan halaman judul berisi judul buku, nama penulis, dan nama penerbit.',
  'ISB-002': 'Tambahkan halaman balik judul (halaman hak cipta) berisi pernyataan hak cipta dan identitas penerbit. ISBN & KDT nanti dicantumkan di sini.',
  'ISB-003': 'Tambahkan kata pengantar/prakata.',
  'ISB-004': 'Tambahkan daftar isi.',
  'ISB-010': 'Hapus/ganti semua teks sementara (TODO, [isi di sini], lorem ipsum) — yang diajukan harus naskah akhir.',
}

function IsbnVerdict({ run, onRerun }: { run: ScreeningRun; onRerun: () => void }) {
  const [items, setItems] = useState<ComplianceItem[] | null>(null)
  useEffect(() => {
    api
      .get<ComplianceItem[]>(`/screenings/${run.id}/compliance`)
      .then(setItems)
      .catch(() => setItems([]))
  }, [run.id])

  const status = run.isbn_status
  const required = (items ?? []).filter((c) => c.blocking)
  const warnings = (items ?? []).filter((c) => !c.blocking && !c.requires_human_verification && c.result_status !== 'not_applicable')
  const docs = (items ?? []).filter((c) => c.requires_human_verification && c.result_status !== 'not_applicable')
  const distribution = (items ?? []).find((c) => c.rule_code === 'ISB-014')
  const needsDistribution = distribution?.observed === 'unknown'
  const failed = required.filter((c) => (c.manual_observed ?? c.observed) === 'fail')
  const verdict =
    status === 'PASS'
      ? {
          tone: 'ok',
          icon: 'checkCircle' as const,
          title: 'Layak diajukan ISBN',
          text: 'Semua syarat naskah yang dapat diperiksa dari berkas sudah terpenuhi.',
        }
      : status === 'FAIL'
        ? {
            tone: 'bad',
            icon: 'xCircle' as const,
            title: 'Belum layak diajukan ISBN',
            text: `${failed.length} syarat wajib belum terpenuhi. Perbaiki naskah lalu unggah versi baru.`,
          }
        : status === 'INCOMPLETE'
          ? {
              tone: 'warn',
              icon: 'alert' as const,
              title: 'Naskah belum terbaca lengkap',
              text: 'Unggah DOCX atau PDF yang teksnya dapat diseleksi (bukan hasil pindai).',
            }
          : needsDistribution
            ? {
                tone: 'warn',
                icon: 'shield' as const,
                title: 'Perlu konfirmasi peredaran',
                text: 'Syarat naskah terpenuhi. Tentukan apakah buku dijual/diedarkan untuk umum.',
              }
            : { tone: 'warn', icon: 'shield' as const, title: 'Perlu ditinjau', text: 'Sebagian aturan wajib belum diverifikasi oleh admin aturan.' }

  return (
    <div className="stack">
      <div className={`verdict ${verdict.tone}`}>
        <Icon name={verdict.icon} size="lg" />
        <div>
          <div className="verdict-title">{verdict.title}</div>
          <div className="small">{verdict.text}</div>
        </div>
        <div className="verdict-actions">
          <ReportBar run={run} />
        </div>
      </div>
      {needsDistribution && <DistributionConfirm run={run} onDone={onRerun} />}
      {run.result_summary_json.classification && <ClassificationCard c={run.result_summary_json.classification} />}
      {!items ? (
        <Skeleton height={160} />
      ) : (
        <div className="grid split">
          <Card title="Syarat naskah (penentu kelayakan)" sub="Peraturan Perpusnas No. 11 Tahun 2025, Pasal 10 ayat (3) huruf b dan c" flush>
            <ul className="checklist">
              {required.map((c) => {
                const observed = c.manual_observed ?? c.observed
                // "unknown" = belum dapat dipastikan dari berkas (mis. rencana peredaran belum dipilih): kuning, bukan gagal.
                const state = observed === 'pass' ? 'ok' : observed === 'fail' ? 'bad' : 'warn'
                return (
                  <li key={c.id} className={state}>
                    <span className="check-icon">
                      <Icon name={state === 'ok' ? 'checkCircle' : state === 'bad' ? 'xCircle' : 'alert'} />
                    </span>
                    <div>
                      <div className="strong">
                        {c.title}
                        {state === 'warn' && (
                          <>
                            {' '}
                            <Pill tone="warn">perlu konfirmasi</Pill>
                          </>
                        )}
                      </div>
                      <div className="small ink-2">{state === 'bad' ? (FIX[c.rule_code] ?? c.explanation) : c.explanation}</div>
                      <div className="xs muted">
                        {c.source_reference} · <span className="mono">{c.rule_code}</span>
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          </Card>
          <div className="stack">
            <Card title="Dokumen yang disiapkan saat pengajuan" sub="Di luar naskah; tidak menentukan kelayakan naskah" flush>
              <ul className="checklist">
                {docs.map((c) => (
                  <li key={c.id} className="todo">
                    <span className="check-icon">
                      <Icon name="file" />
                    </span>
                    <div>
                      <div className="strong small">{c.title}</div>
                      <div className="xs muted">{c.source_reference}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
            {warnings.length > 0 && (
              <Card title="Catatan tambahan" sub="Tidak menentukan kelayakan" flush>
                <ul className="checklist">
                  {warnings.map((c) => {
                    const ok = c.observed === 'pass'
                    return (
                      <li key={c.id} className={ok ? 'ok' : 'warn'}>
                        <span className="check-icon">
                          <Icon name={ok ? 'checkCircle' : 'alert'} />
                        </span>
                        <div>
                          <div className="strong small">{c.title}</div>
                          <div className="xs ink-2">{c.explanation}</div>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </Card>
            )}
          </div>
        </div>
      )}
      <div className="row between">
        <p className="xs muted" style={{ maxWidth: 760 }}>
          Hasil ini menilai kelengkapan naskah terhadap persyaratan dokumen pengajuan ISBN. Keputusan pemberian ISBN tetap ada pada verifikasi Perpusnas.
        </p>
        <button className="sm ghost" onClick={onRerun}>
          <Icon name="refresh" size="sm" />
          Periksa ulang
        </button>
      </div>
    </div>
  )
}

const FIELDS: { key: Exclude<keyof Classification, 'source' | 'applied' | 'manual_type'>; label: string }[] = [
  { key: 'jenis_terbitan', label: 'Jenis terbitan' },
  { key: 'jenis_pustaka', label: 'Jenis pustaka' },
  { key: 'kelompok_pembaca', label: 'Kelompok pembaca' },
  { key: 'kategori_buku', label: 'Kategori buku' },
  { key: 'terjemahan', label: 'Terjemahan' },
  { key: 'penelitian', label: 'Penelitian' },
  { key: 'kategori_penerbit', label: 'Kategori terbitan' },
  { key: 'peredaran', label: 'Peredaran' },
  { key: 'media', label: 'Media' },
]

const CONF_TONE = { tinggi: 'ok', sedang: 'info', rendah: 'neutral' } as const

/** Kategori terbitan sesuai ruas formulir pengajuan ISBN, ditentukan otomatis dari isi naskah. */
function ClassificationCard({ c }: { c: Classification }) {
  return (
    <Card
      title="Kategori terbitan"
      sub={
        c.applied
          ? 'Ditentukan otomatis dari isi naskah — dipakai untuk aturan ISBN dan rubrik cek layout. Gunakan nilai ini saat mengisi formulir ISBN.'
          : `Jenis naskah dipilih manual; sistem mendeteksi “${c.jenis_terbitan.label ?? c.jenis_terbitan.value}”.`
      }
      flush
    >
      <div className="class-grid">
        {FIELDS.map((f) => {
          const item: ClassItem | undefined = c[f.key]
          if (!item) return null
          return (
            <div key={f.key} className="class-item">
              <div className="xs muted">{f.label}</div>
              <div className="row" style={{ gap: '0.4rem' }}>
                <span className="strong">{item.label ?? item.value}</span>
                <Pill tone={CONF_TONE[item.confidence]}>{item.confidence}</Pill>
              </div>
              <div className="xs ink-2">{item.reasons.join(' · ')}</div>
            </div>
          )
        })}
      </div>
      <div className="table-foot xs">Dasar: {c.source}. Jenis naskah dapat diubah manual di tab Metadata &amp; penulis.</div>
    </Card>
  )
}

/** Konfirmasi rencana peredaran (ISB-014) langsung dari kartu hasil, lalu periksa ulang. */
function DistributionConfirm({ run, onDone }: { run: ScreeningRun; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const choose = async (value: string) => {
    setBusy(true)
    setError(null)
    try {
      const m = await api.get<{ metadata_json: Record<string, unknown> }>(`/manuscripts/${run.manuscript_id}`)
      await api.patch(`/manuscripts/${run.manuscript_id}`, { metadata: { ...m.metadata_json, distribution: value } })
      onDone()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card
      title="Bagaimana buku ini akan diedarkan?"
      sub="ISBN hanya untuk terbitan yang tersedia bagi masyarakat umum. Novel, biografi, buku anak, dan antologi harus dijual untuk umum (Juknis 4.5.1.3)."
    >
      <div className="row">
        <button className="primary" disabled={busy} onClick={() => void choose('dijual_umum')}>
          Dijual untuk umum
        </button>
        <button disabled={busy} onClick={() => void choose('gratis_umum')}>
          Gratis, dapat diakses umum
        </button>
        <button disabled={busy} onClick={() => void choose('terbatas')}>
          Cetak terbatas / kalangan tertentu
        </button>
        {error && (
          <span className="xs" style={{ color: 'var(--bad-text)' }}>
            {error}
          </span>
        )}
      </div>
    </Card>
  )
}
