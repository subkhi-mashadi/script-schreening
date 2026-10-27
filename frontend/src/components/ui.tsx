import type { ReactNode } from 'react'
import { EXTRACTION_LABELS } from '../labels'
import { Icon, type IconName } from './icons'

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'neutral'

/** Status ekstraksi → nada, ikon, label. Status selalu ikon + teks, tidak hanya warna (PRD §17.5). */
const EXTRACTION_TONE: Record<string, { tone: Tone; icon: IconName }> = {
  PENDING: { tone: 'neutral', icon: 'clock' },
  PROCESSING: { tone: 'info', icon: 'loader' },
  EXTRACTED: { tone: 'ok', icon: 'checkCircle' },
  INCOMPLETE: { tone: 'warn', icon: 'alert' },
  FAILED: { tone: 'bad', icon: 'xCircle' },
}

export function Pill({ tone = 'neutral', icon, children }: { tone?: Tone; icon?: IconName; children: ReactNode }) {
  return (
    <span className={`pill ${tone}`}>
      {icon && <Icon name={icon} />}
      {children}
    </span>
  )
}

export function ExtractionBadge({ status }: { status: string | null | undefined }) {
  if (!status)
    return (
      <Pill tone="neutral" icon="inbox">
        Belum ada berkas
      </Pill>
    )
  const t = EXTRACTION_TONE[status] ?? { tone: 'neutral', icon: 'info' }
  return (
    <Pill tone={t.tone} icon={t.icon}>
      {EXTRACTION_LABELS[status] ?? status}
    </Pill>
  )
}

/** Badge lama: dipertahankan sebagai alias Pill tanpa ikon. */
export function Badge({ tone = 'neutral', children }: { tone?: string; children: ReactNode }) {
  return <Pill tone={tone as Tone}>{children}</Pill>
}

export function Tag({ children }: { children: ReactNode }) {
  return <span className="tag">{children}</span>
}

const ALERT_ICON: Record<string, IconName> = { ok: 'checkCircle', warn: 'alert', bad: 'xCircle', info: 'info' }

export function Alert({ tone = 'bad', title, children }: { tone?: 'bad' | 'warn' | 'info' | 'ok'; title?: string; children?: ReactNode }) {
  return (
    <div className={`alert ${tone}`} role={tone === 'bad' ? 'alert' : 'status'}>
      <Icon name={ALERT_ICON[tone]} />
      <div className="alert-body">
        {title && <strong>{title}</strong>}
        {children}
      </div>
    </div>
  )
}

export function PageHeader({ eyebrow, title, sub, actions }: { eyebrow?: ReactNode; title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  )
}

export function Card({
  title,
  sub,
  action,
  children,
  flush,
  className = '',
}: {
  title?: ReactNode
  sub?: ReactNode
  action?: ReactNode
  children: ReactNode
  flush?: boolean
  className?: string
}) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <div className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {sub && <p className="sub">{sub}</p>}
          </div>
          {action}
        </div>
      )}
      <div className={`card-body ${flush ? 'flush' : ''}`}>{children}</div>
    </section>
  )
}

export function Kpi({
  label,
  value,
  unit,
  icon,
  tone,
  foot,
}: {
  label: string
  value: ReactNode
  unit?: string
  icon: IconName
  tone?: 'ok' | 'warn' | 'brand'
  foot?: ReactNode
}) {
  return (
    <div className="card kpi">
      <div className="kpi-top">
        <span>{label}</span>
        <span className={`kpi-icon ${tone ?? ''}`}>
          <Icon name={icon} size="sm" />
        </span>
      </div>
      <div className="kpi-value">
        {value}
        {unit && <span className="unit">{unit}</span>}
      </div>
      {foot && <div className="kpi-foot">{foot}</div>}
    </div>
  )
}

export function Empty({ icon = 'inbox', title, children }: { icon?: IconName; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <Icon name={icon} size="lg" />
      <strong>{title}</strong>
      {children && <div className="small">{children}</div>}
    </div>
  )
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  return (
    <div className="table-foot">
      <span className="num">
        {from}–{to} dari {total}
      </span>
      {pages > 1 && (
        <div className="pager">
          <button className="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            Sebelumnya
          </button>
          <span className="num">
            {page} / {pages}
          </span>
          <button className="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
            Berikutnya
          </button>
        </div>
      )}
    </div>
  )
}

export function Tabs<T extends string>({ tabs, active, onChange }: { tabs: { key: T; label: string; count?: number }[]; active: T; onChange: (k: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={active === t.key} className={active === t.key ? 'active' : ''} onClick={() => onChange(t.key)}>
          {t.label}
          {t.count !== undefined && <span className="tag">{t.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function Skeleton({ height = 16, width = '100%' }: { height?: number; width?: number | string }) {
  return <div className="skeleton" style={{ height, width }} />
}

export function Spinner({ label = 'Memuat…' }: { label?: string }) {
  return (
    <div className="stack" aria-busy="true" aria-label={label}>
      <Skeleton height={28} width="40%" />
      <Skeleton height={120} />
      <Skeleton height={120} />
    </div>
  )
}
