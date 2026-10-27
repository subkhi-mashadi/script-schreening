import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { Icon } from '../components/icons'
import { EditorialBadge, IsbnBadge } from '../components/status'
import { Alert, Card, Empty, ExtractionBadge, PageHeader, Pager, Pill, Skeleton, Tag } from '../components/ui'
import { FIELD_LABELS, INTAKE_LABELS, fmtRelative } from '../labels'
import type { ManuscriptListItem, Options, Page } from '../types'

export default function ManuscriptsPage() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState<Page<ManuscriptListItem> | null>(null)
  const [options, setOptions] = useState<Options | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState(params.get('q') ?? '')

  const query = params.toString()
  const filters = Object.fromEntries(params.entries())
  const page = Number(params.get('page') ?? 1)
  const filtered = ['q', 'manuscript_type', 'extraction_status', 'date_from', 'date_to'].some((k) => filters[k])

  useEffect(() => {
    api
      .get<Options>('/manuscripts/options')
      .then(setOptions)
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    api
      .get<Page<ManuscriptListItem>>('/manuscripts', Object.fromEntries(new URLSearchParams(query).entries()))
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [query])

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('page')
    setParams(next)
  }

  const typeLabel = (v: string) => options?.manuscript_types.find((t) => t.value === v)?.label ?? v

  return (
    <div className="container">
      <PageHeader
        title="Naskah"
        sub={data ? `${data.total} naskah dalam cakupan akses Anda` : 'Memuat…'}
        actions={
          can('manuscript.create') && (
            <>
              <Link className="button" to="/naskah/baru">
                <Icon name="plus" size="sm" />
                Rekam manual
              </Link>
              <Link className="button primary" to="/">
                <Icon name="upload" size="sm" />
                Cek naskah
              </Link>
            </>
          )
        }
      />
      {error && <Alert>{error}</Alert>}
      <Card flush>
        <form
          className="toolbar"
          onSubmit={(e) => {
            e.preventDefault()
            setFilter('q', q)
          }}
        >
          <div className="input-icon grow">
            <Icon name="search" size="sm" />
            <input placeholder="Cari judul, kode, atau penulis" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Cari naskah" />
          </div>
          <select value={filters.manuscript_type ?? ''} onChange={(e) => setFilter('manuscript_type', e.target.value)} aria-label="Jenis naskah">
            <option value="">Semua jenis</option>
            {options?.manuscript_types.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <select value={filters.extraction_status ?? ''} onChange={(e) => setFilter('extraction_status', e.target.value)} aria-label="Status pembacaan">
            <option value="">Semua status</option>
            {options?.extraction_statuses.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <input
            type="date"
            value={filters.date_from ?? ''}
            onChange={(e) => setFilter('date_from', e.target.value)}
            aria-label="Masuk sejak"
            title="Masuk sejak"
          />
          <input
            type="date"
            value={filters.date_to ?? ''}
            onChange={(e) => setFilter('date_to', e.target.value)}
            aria-label="Masuk sampai"
            title="Masuk sampai"
          />
          {filtered && (
            <button
              type="button"
              className="ghost sm"
              onClick={() => {
                setQ('')
                setParams(new URLSearchParams())
              }}
            >
              Hapus filter
            </button>
          )}
        </form>

        {!data ? (
          <div className="card-body stack">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} height={40} />
            ))}
          </div>
        ) : data.items.length === 0 ? (
          <Empty icon="book" title={filtered ? 'Tidak ada naskah yang cocok' : 'Belum ada naskah'}>
            {filtered ? 'Ubah atau hapus filter.' : can('manuscript.create') && <Link to="/">Unggah naskah pertama →</Link>}
          </Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Naskah</th>
                    <th>Jenis</th>
                    <th>Editor</th>
                    <th>Status pembacaan</th>
                    <th>Kelayakan ISBN</th>
                    <th className="num">Skor layout</th>
                    <th>Masuk</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((m) => (
                    <tr key={m.id} className="clickable" onClick={() => navigate(`/naskah/${m.id}`)}>
                      <td style={{ maxWidth: 420 }}>
                        <Link to={`/naskah/${m.id}`} className="cell-title" onClick={(e) => e.stopPropagation()}>
                          {m.working_title}
                        </Link>
                        <div className="cell-sub">
                          <span className="mono">{m.internal_code}</span> · {m.authors.map((a) => a.author_name).join(', ') || 'Penulis belum diisi'}
                        </div>
                        {(m.incomplete_fields.length > 0 || m.intake_status !== 'RECEIVED') && (
                          <div className="row" style={{ marginTop: 4 }}>
                            {m.intake_status !== 'RECEIVED' && <Pill>{INTAKE_LABELS[m.intake_status] ?? m.intake_status}</Pill>}
                            {m.incomplete_fields.length > 0 && (
                              <Pill tone="warn" icon="edit">
                                Kosong: {m.incomplete_fields.map((f) => FIELD_LABELS[f] ?? f).join(', ')}
                              </Pill>
                            )}
                          </div>
                        )}
                      </td>
                      <td>
                        <Tag>{typeLabel(m.manuscript_type)}</Tag>
                      </td>
                      <td className="ink-2">{m.assigned_editor?.full_name ?? <span className="muted">—</span>}</td>
                      <td>
                        <ExtractionBadge status={m.latest_version?.extraction_status} />
                        {m.latest_version && <div className="cell-sub">Versi {m.latest_version.version_number}</div>}
                      </td>
                      <td>
                        {m.latest_screening ? <IsbnBadge value={m.latest_screening.isbn_status} /> : <span className="muted small">Belum diperiksa</span>}
                      </td>
                      <td className="num">
                        <span className="strong">{m.latest_layout?.total_score ?? '—'}</span>
                        {m.latest_layout ? (
                          <div className="cell-sub">
                            <EditorialBadge value={m.latest_layout.editorial_status} />
                          </div>
                        ) : (
                          <div className="cell-sub">Belum dicek</div>
                        )}
                      </td>
                      <td className="nowrap muted small">{fmtRelative(m.submitted_at ?? m.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={page} pageSize={data.page_size} total={data.total} onPage={(p) => setFilter('page', String(p))} />
          </>
        )}
      </Card>
    </div>
  )
}
