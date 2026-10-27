/**
 * Chart SVG ringan tanpa library.
 * Spesifikasi: bar ≤ 24px dengan ujung data membulat 4px, grid hairline, satu sumbu,
 * hover tooltip per mark, label teks memakai token tinta (bukan warna seri),
 * dan setiap chart punya tampilan tabel sebagai alternatif.
 */
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Icon, type IconName } from './icons'

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

function niceMax(v: number): number {
  if (v <= 4) return 4
  const pow = 10 ** Math.floor(Math.log10(v))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => v / s <= 4) ?? 10 * pow
  return Math.ceil(v / step) * step
}

/** Kolom vertikal dengan sudut atas membulat 4px dan dasar persegi. */
function columnPath(x: number, y: number, w: number, h: number): string {
  if (h <= 0) return ''
  const r = Math.min(4, w / 2, h)
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}

export interface ColumnDatum {
  key: string
  label: string
  tooltip: string
  value: number
}

export function ColumnChart({ data, height = 200, unit, tickEvery = 2 }: { data: ColumnDatum[]; height?: number; unit: string; tickEvery?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const padL = 28
  const padB = 24
  const padT = 18
  const plotW = Math.max(0, width - padL)
  const plotH = height - padB - padT
  const max = niceMax(Math.max(0, ...data.map((d) => d.value)))
  const ticks = [0, max / 4, max / 2, (3 * max) / 4, max].filter((t) => Number.isInteger(t))
  const band = data.length ? plotW / data.length : 0
  const barW = Math.min(24, band * 0.62)
  const y = (v: number) => padT + plotH - (v / max) * plotH
  const peak = data.reduce((best, d, i) => (d.value > (data[best]?.value ?? -1) ? i : best), 0)

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`Diagram kolom: ${data.map((d) => `${d.tooltip} ${d.value}`).join(', ')}`}>
          {ticks.map((t) => (
            <g key={t}>
              <line className={t === 0 ? 'base-line' : 'grid-line'} x1={padL} x2={width} y1={y(t)} y2={y(t)} />
              <text x={padL - 8} y={y(t)} dy="0.32em" textAnchor="end">
                {t}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const x = padL + i * band + (band - barW) / 2
            const h = (d.value / max) * plotH
            return (
              <g key={d.key}>
                <path className={`bar ${hover !== null && hover !== i ? 'dim' : ''}`} d={columnPath(x, y(d.value), barW, h)} />
                {i === peak && d.value > 0 && hover === null && (
                  <text className="value-label" x={x + barW / 2} y={y(d.value) - 6} textAnchor="middle">
                    {d.value}
                  </text>
                )}
                {i % tickEvery === (data.length - 1) % tickEvery && (
                  <text x={x + barW / 2} y={height - 6} textAnchor="middle">
                    {d.label}
                  </text>
                )}
                {/* Target hover selebar band, lebih besar dari mark. */}
                <rect
                  x={padL + i * band}
                  y={padT}
                  width={band}
                  height={plotH}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                />
              </g>
            )
          })}
        </svg>
      )}
      {hover !== null && data[hover] && (
        <div className="tooltip" style={{ left: padL + hover * band + band / 2, top: y(data[hover].value) }}>
          <strong className="num">
            {data[hover].value} {unit}
          </strong>
          {data[hover].tooltip}
        </div>
      )}
      <ChartTable head={['Tanggal', unit]} rows={data.map((d) => [d.tooltip, d.value])} />
    </div>
  )
}

export interface StackDatum {
  key: string
  label: string
  value: number
  color: string
  icon: IconName
  href?: string
}

/** Komposisi status sebagai satu batang 100% + legenda berikon (status tidak pernah hanya warna). */
export function StatusStack({ data, renderLink }: { data: StackDatum[]; renderLink?: (d: StackDatum, label: ReactNode) => ReactNode }) {
  const [hover, setHover] = useState<string | null>(null)
  const total = data.reduce((s, d) => s + d.value, 0)
  const visible = data.filter((d) => d.value > 0)
  const pct = (v: number) => (total ? Math.round((v / total) * 100) : 0)
  return (
    <div>
      <div className={`stackbar ${hover ? 'hovering' : ''}`} role="img" aria-label={data.map((d) => `${d.label} ${d.value}`).join(', ')}>
        {visible.map((d) => (
          <span
            key={d.key}
            className={hover === d.key ? 'hover' : ''}
            style={{ width: `${(d.value / total) * 100}%`, background: d.color }}
            onMouseEnter={() => setHover(d.key)}
            onMouseLeave={() => setHover(null)}
            title={`${d.label}: ${d.value} (${pct(d.value)}%)`}
          />
        ))}
      </div>
      <ul className="legend">
        {data.map((d) => {
          const label = <span className="ink-2">{d.label}</span>
          return (
            <li key={d.key} className={hover === d.key ? 'hover' : ''} onMouseEnter={() => setHover(d.key)} onMouseLeave={() => setHover(null)}>
              <span style={{ color: d.color }}>
                <Icon name={d.icon} />
              </span>
              {renderLink ? renderLink(d, label) : label}
              <span className="num strong">{d.value}</span>
              <span className="pct num">{pct(d.value)}%</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function BarList({ data, unit }: { data: { key: string; label: string; value: number }[]; unit: string }) {
  const max = Math.max(1, ...data.map((d) => d.value))
  return (
    <ul className="barlist" aria-label={`Jumlah ${unit} per kategori`}>
      {data.map((d) => (
        <li key={d.key}>
          <span className="ink-2 truncate">{d.label}</span>
          <span className="num strong">{d.value}</span>
          <div className="track">
            <div className="fill" style={{ width: `${(d.value / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  )
}

function ChartTable({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <details className="chart-table">
      <summary>Tampilkan sebagai tabel</summary>
      <table className="table bordered">
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={h} className={i > 0 ? 'num' : ''}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={String(r[0])}>
              {r.map((c, i) => (
                <td key={i} className={i > 0 ? 'num' : ''}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  )
}
