import { useEffect, useState, type FormEvent } from 'react'
import { api, errorMessage } from '../api'
import type { Author, Manuscript, Options, UserBrief } from '../types'
import { Icon } from './icons'
import { Alert } from './ui'

export interface ManuscriptPayload {
  working_title: string
  manuscript_type: string
  language_code: string
  submitted_at: string | null
  assigned_editor_id: string | null
  authors: Author[]
  metadata: Record<string, unknown>
}

function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export default function ManuscriptForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: Manuscript
  submitLabel: string
  onSubmit: (p: ManuscriptPayload) => Promise<void>
  onCancel?: () => void
}) {
  const [options, setOptions] = useState<Options | null>(null)
  const [editors, setEditors] = useState<UserBrief[]>([])
  const [title, setTitle] = useState(initial?.working_title ?? '')
  const [type, setType] = useState(initial?.manuscript_type ?? '')
  const [lang, setLang] = useState(initial?.language_code ?? 'id')
  const [submitted, setSubmitted] = useState(toLocalInput(initial?.submitted_at))
  const [editor, setEditor] = useState(initial?.assigned_editor?.id ?? '')
  const [authors, setAuthors] = useState<Author[]>(initial?.authors.length ? initial.authors : [{ author_name: '' }])
  const [synopsis, setSynopsis] = useState(String(initial?.metadata_json?.synopsis ?? ''))
  const [distribution, setDistribution] = useState(String(initial?.metadata_json?.distribution ?? ''))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .get<Options>('/manuscripts/options')
      .then(setOptions)
      .catch((e) => setError(errorMessage(e)))
    api
      .get<UserBrief[]>('/users/editors')
      .then(setEditors)
      .catch(() => setEditors([]))
  }, [])

  const setAuthor = (i: number, patch: Partial<Author>) => setAuthors((as) => as.map((a, j) => (j === i ? { ...a, ...patch } : a)))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSubmit({
        working_title: title,
        manuscript_type: type,
        language_code: lang,
        // Tanggal masuk dikirim sebagai tengah hari waktu lokal agar tidak bergeser hari saat dikonversi ke UTC.
        submitted_at: submitted ? new Date(`${submitted}T12:00:00`).toISOString() : null,
        assigned_editor_id: editor || null,
        authors: authors
          .filter((a) => a.author_name.trim())
          .map((a) => ({ author_name: a.author_name.trim(), author_email: a.author_email || null, affiliation: a.affiliation || null })),
        metadata: { ...(initial?.metadata_json ?? {}), synopsis: synopsis || undefined, distribution: distribution || undefined },
      })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      {error && <Alert>{error}</Alert>}
      <label className="field">
        <span>Judul kerja *</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={1000} />
      </label>
      <div className="grid2">
        <label className="field">
          <span>Jenis naskah *</span>
          <select value={type} onChange={(e) => setType(e.target.value)} required>
            <option value="">— Pilih —</option>
            {options?.manuscript_types.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Bahasa *</span>
          <select value={lang} onChange={(e) => setLang(e.target.value)}>
            {options?.languages.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Tanggal masuk</span>
          <input type="date" value={submitted} onChange={(e) => setSubmitted(e.target.value)} />
        </label>
        <label className="field">
          <span>Editor yang ditugaskan</span>
          <select value={editor} onChange={(e) => setEditor(e.target.value)}>
            <option value="">— Belum ditugaskan —</option>
            {editors.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <fieldset>
        <legend>Penulis (urutan sesuai daftar)</legend>
        {authors.map((a, i) => (
          <div className="author-row" key={i}>
            <span className="muted">{i + 1}.</span>
            <input
              placeholder="Nama penulis"
              value={a.author_name}
              onChange={(e) => setAuthor(i, { author_name: e.target.value })}
              aria-label={`Nama penulis ${i + 1}`}
            />
            <input
              placeholder="Email (opsional)"
              type="email"
              value={a.author_email ?? ''}
              onChange={(e) => setAuthor(i, { author_email: e.target.value })}
              aria-label={`Email penulis ${i + 1}`}
            />
            <input
              placeholder="Afiliasi (opsional)"
              value={a.affiliation ?? ''}
              onChange={(e) => setAuthor(i, { affiliation: e.target.value })}
              aria-label={`Afiliasi penulis ${i + 1}`}
            />
            <button type="button" className="link" onClick={() => setAuthors((as) => as.filter((_, j) => j !== i))} disabled={authors.length === 1}>
              Hapus
            </button>
          </div>
        ))}
        <button type="button" className="sm" onClick={() => setAuthors((as) => [...as, { author_name: '' }])}>
          <Icon name="plus" size="sm" />
          Tambah penulis
        </button>
      </fieldset>

      <label className="field">
        <span>Sinopsis / catatan penerimaan</span>
        <textarea rows={3} value={synopsis} onChange={(e) => setSynopsis(e.target.value)} maxLength={5000} />
      </label>
      <label className="field">
        <span>
          Rencana peredaran buku <span className="hint">menentukan kelayakan ISBN</span>
        </span>
        <select value={distribution} onChange={(e) => setDistribution(e.target.value)}>
          <option value="">Belum ditentukan</option>
          {options?.distribution_options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <div className="row">
        <button className="primary" disabled={busy}>
          <Icon name="check" size="sm" />
          {busy ? 'Menyimpan…' : submitLabel}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel}>
            Batal
          </button>
        )}
      </div>
      <p className="muted small">Kolom yang kosong ditandai sebagai metadata belum lengkap — sistem tidak mengisinya dengan asumsi.</p>
    </form>
  )
}
