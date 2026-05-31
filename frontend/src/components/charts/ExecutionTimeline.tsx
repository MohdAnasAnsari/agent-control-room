import { useState } from 'react'
import { useDarkMode } from '../../hooks/useDarkMode'
import type { TimelineDataPoint } from '../../types'

interface Props {
  data: TimelineDataPoint[]
  loading?: boolean
}

// Build an SVG polyline path string from [x,y] coords
function polyPath(pts: [number, number][]): string {
  return pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
}

// Build closed area path (polyline + close down to baseline)
function areaPath(pts: [number, number][], baseline: number): string {
  if (pts.length === 0) return ''
  const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
  const close = ` L ${pts[pts.length - 1][0].toFixed(1)} ${baseline} L ${pts[0][0].toFixed(1)} ${baseline} Z`
  return line + close
}

const W = 800
const H = 200
const PAD_L = 32
const PAD_R = 12
const PAD_T = 16
const PAD_B = 28
const CW = W - PAD_L - PAD_R   // chart width
const CH = H - PAD_T - PAD_B   // chart height

export default function ExecutionTimeline({ data, loading = false }: Props) {
  const dark = useDarkMode()
  const [tooltip, setTooltip] = useState<{ x: number; y: number; d: TimelineDataPoint } | null>(null)

  const gridColor  = dark ? '#374151' : '#E5E7EB'
  const textColor  = dark ? '#9CA3AF' : '#6B7280'

  if (loading) {
    return <div className="h-[200px] rounded-lg skeleton" aria-hidden="true" />
  }

  if (data.length === 0) return null

  const maxVal = Math.max(...data.map(d => d.success + d.failed), 1)
  const yMax   = Math.ceil(maxVal / 5) * 5   // round up to nearest 5

  const toX = (i: number) => PAD_L + (i / (data.length - 1)) * CW
  const toY = (v: number) => PAD_T + (1 - v / yMax) * CH

  const successPts: [number, number][] = data.map((d, i) => [toX(i), toY(d.success)])
  const failedPts:  [number, number][] = data.map((d, i) => [toX(i), toY(d.failed)])
  const baseline = PAD_T + CH

  // X-axis labels: show every 5th
  const xLabels = data.reduce<{ i: number; label: string }[]>((acc, d, i) => {
    if (i === 0 || i === data.length - 1 || i % 5 === 0) acc.push({ i, label: d.date })
    return acc
  }, [])

  // Y-axis ticks
  const yTicks = Array.from({ length: 4 }, (_, k) => Math.round((yMax / 3) * k))

  return (
    <div className="relative" onMouseLeave={() => setTooltip(null)}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Execution timeline chart"
        style={{ display: 'block' }}
      >
        <defs>
          <linearGradient id="successGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3B82F6" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#3B82F6" stopOpacity="0.02" />
          </linearGradient>
          <linearGradient id="failedGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#EF4444" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#EF4444" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Horizontal grid lines */}
        {yTicks.map(v => (
          <g key={v}>
            <line
              x1={PAD_L} y1={toY(v)} x2={PAD_L + CW} y2={toY(v)}
              stroke={gridColor} strokeWidth="1" strokeDasharray="3 3"
            />
            <text
              x={PAD_L - 6} y={toY(v)} textAnchor="end" dominantBaseline="middle"
              fontSize="10" fill={textColor}
            >{v}</text>
          </g>
        ))}

        {/* X-axis labels */}
        {xLabels.map(({ i, label }) => (
          <text
            key={i}
            x={toX(i)} y={baseline + 14}
            textAnchor="middle" fontSize="10" fill={textColor}
          >{label}</text>
        ))}

        {/* Area fills */}
        <path d={areaPath(successPts, baseline)} fill="url(#successGrad)" />
        <path d={areaPath(failedPts, baseline)}  fill="url(#failedGrad)" />

        {/* Lines */}
        <path d={polyPath(successPts)} fill="none" stroke="#3B82F6" strokeWidth="2" strokeLinejoin="round" />
        <path d={polyPath(failedPts)}  fill="none" stroke="#EF4444" strokeWidth="2" strokeLinejoin="round" />

        {/* Hover overlay — invisible rects per column */}
        {data.map((d, i) => {
          const cx = toX(i)
          const colW = CW / (data.length - 1)
          return (
            <rect
              key={i}
              x={cx - colW / 2}
              y={PAD_T}
              width={colW}
              height={CH}
              fill="transparent"
              className="cursor-crosshair"
              onMouseEnter={e => {
                const svgEl = (e.currentTarget as SVGRectElement).ownerSVGElement!
                const rect = svgEl.getBoundingClientRect()
                const scaleX = rect.width  / W
                const scaleY = rect.height / H
                setTooltip({
                  x: cx * scaleX + rect.left,
                  y: toY(Math.max(d.success, d.failed)) * scaleY + rect.top,
                  d,
                })
              }}
            />
          )
        })}

        {/* Hover dot */}
        {tooltip && (() => {
          const i = data.indexOf(tooltip.d)
          if (i < 0) return null
          return (
            <g>
              <circle cx={toX(i)} cy={toY(tooltip.d.success)} r="4" fill="#3B82F6" />
              <circle cx={toX(i)} cy={toY(tooltip.d.failed)}  r="4" fill="#EF4444" />
            </g>
          )
        })()}
      </svg>

      {/* Tooltip bubble */}
      {tooltip && (
        <div
          className="fixed z-50 pointer-events-none px-3 py-2 rounded-lg bg-gray-900 dark:bg-gray-700 text-white text-xs shadow-lg border border-gray-700 dark:border-gray-600"
          style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}
        >
          <p className="font-semibold mb-1">{tooltip.d.date}</p>
          <p className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-blue-400 inline-block" />
            Success: <strong>{tooltip.d.success}</strong>
          </p>
          <p className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-red-400 inline-block" />
            Failed: <strong>{tooltip.d.failed}</strong>
          </p>
        </div>
      )}
    </div>
  )
}
