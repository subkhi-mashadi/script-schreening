import { useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { BLOCK_LABELS } from '../labels'
import type { Page, Section, Version, VersionBrief } from '../types'
import { Icon } from './icons'
import { Alert, Empty, ExtractionBadge, Pager, Skeleton } from './ui'

const READY = new Set(['EXTRACTED', 'INCOMPLETE'])

export default function StructureViewer({ versions }: { versions: VersionBrief[] }) {
  const usable = versions.filter((v) => READY.has(v.extraction_status))
  const [versionId, setVersionId] = useState(usable.at(-1)?.id ?? '')
  const [version, setVersion] = useState<Version | null>(null)
  const [sections, setSections] = useState<Page<Section> | null>(null)
  const [filters, setFilters] = useState({ section_type: '', section_path: '', page_number: '', q: '' })
  const [page, setPage] = useState(1)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!versionId) return
    api
      .get<Version>(`/versions/${versionId}`)
      .then(setVersion)
      .catch((e) => setError(errorMessage(e)))
  }, [versionId])

  useEffect(() => {
    if (!versionId) return
    api
      .get<Page<Section>>(`/versions/${versionId}/sections`, { ...filters, page, page_size: 100 })
      .then(setSections)
      .catch((e) => setError(errorMessage(e)))
  }, [versionId, filters, page])

  if (!usable.length) return <Empty icon="file" title="Belum ada versi dengan hasil pembacaan" />

  const update = (patch: Partial<typeof filters>) => {
    setFilters((f) => ({ ...f, ...patch }))
    setPage(1)
  }
  const headings = version?.extraction_summary_json.headings ?? []
  const reliablePages = version?.extraction_summary_json.page_numbers_reliable

  return (
    <div className="stack">
      {usable.length > 1 && (
        <div className="row">
          <span className="strong small">Versi</span>
          <select value={versionId} onChange={(e) => setVersionId(e.target.value)} aria-label="Versi">
            {[...usable].reverse().map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_number} — {v.original_filename}
              </option>
            ))}
          </select>
          {version && <ExtractionBadge status={version.extraction_status} />}
        </div>
      )}
      {error && <Alert>{error}</Alert>}

      <div className="viewer">
        <aside className="card outline" aria-label="Kerangka naskah">
          <div className="outline-title">Kerangka</div>
          <button className={!filters.section_path ? 'active' : ''} onClick={() => update({ section_path: '' })}>
            Seluruh naskah
          </button>
          {headings.map((h) => (
            <button
              key={h.block_id}
              className={filters.section_path === h.section_path ? 'active' : ''}
              style={{ paddingLeft: `${0.5 + (h.level - 1) * 0.85}rem` }}
              onClick={() => update({ section_path: h.section_path ?? '' })}
            >
              {h.text}
              {h.page_number ? <span className="muted xs"> · h.{h.page_number}</span> : null}
            </button>
          ))}
        </aside>

        <div className="card" style={{ minWidth: 0 }}>
          <div className="toolbar">
            <div className="input-icon grow">
              <Icon name="search" size="sm" />
              <input placeholder="Cari teks dalam naskah" value={filters.q} onChange={(e) => update({ q: e.target.value })} aria-label="Cari teks" />
            </div>
            <select value={filters.section_type} onChange={(e) => update({ section_type: e.target.value })} aria-label="Jenis blok">
              <option value="">Semua jenis blok</option>
              {Object.entries(BLOCK_LABELS).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
            {reliablePages && (
              <input
                type="number"
                min={1}
                placeholder="Halaman"
                style={{ width: 110 }}
                value={filters.page_number}
                onChange={(e) => update({ page_number: e.target.value })}
                aria-label="Halaman"
              />
            )}
          </div>
          {filters.section_path && (
            <div className="toolbar small">
              <span className="muted">Bagian:</span> <span className="strong">{filters.section_path}</span>
              <button className="link" onClick={() => update({ section_path: '' })}>
                Hapus
              </button>
            </div>
          )}
          {!sections ? (
            <div className="card-body stack">
              <Skeleton height={60} />
              <Skeleton height={60} />
            </div>
          ) : sections.items.length === 0 ? (
            <Empty icon="search" title="Tidak ada bagian yang cocok" />
          ) : (
            <>
              {sections.items.map((s) => (
                <article key={s.id} className={`blk ${s.section_type}`} data-level={s.heading_level ?? undefined}>
                  <header className="loc">
                    <span className="mono">{s.block_id}</span>
                    <span>{BLOCK_LABELS[s.section_type] ?? s.section_type}</span>
                    {s.page_number ? (
                      <span>Halaman {s.page_number}</span>
                    ) : s.locator_json.page_estimate ? (
                      <span>± halaman {String(s.locator_json.page_estimate)}</span>
                    ) : null}
                    {s.section_path && <span className="path">{s.section_path}</span>}
                  </header>
                  <div className="txt">{s.text_content}</div>
                </article>
              ))}
              <Pager page={page} pageSize={sections.page_size} total={sections.total} onPage={setPage} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
