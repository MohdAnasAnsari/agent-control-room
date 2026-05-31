import { useState } from 'react'
import { useDarkMode } from '../../hooks/useDarkMode'
import type { TokenDataPoint } from '../../types'

interface Props {
  data: TokenDataPoint[]
  loading?: boolean
}

const W = 500
const H = 200
const PAD_L = 40
const PAD_R = 12
const PAD_T = 16
const PAD_B = 28
const CW = W - PAD_L - PAD_R
const CH = H - PAD_T - PAD_B

function fmtK(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(0)}K` : String(n)
}

export default function TokenUsageChart({ data, loading = false }: Props) {
  const dark = useDarkMode()
  const [tooltip, setTooltip] = useState<{ x: number; y: number; d: TokenDataPoint } | null>(null)

  const gridColor = dark ? '#374151' : '#E5E7EB'
  const textColor = dark ? '#9CA3AF' : '#6B7280'

  if (loading) {
    return <div className="h-[200px] rounded-lg skeleton" aria-hidden="true" />
  }

  if (data.length === 0) return null

  const maxTotal = Math.max(...data.map(d => d.input + d.output), 1)
  const yMax = Math.ceil(maxTotal / 5000) * 5000

  const n = data.length
  const BAR_GAP   = 0.3
  const BAR_W     = (CW / n) * (1 - BAR_GAP)
  const BAR_SPACE = CW / n

  const toY = (v: number) => PAD_T + (1 - v / yMax) * CH
  const barX = (i: number) => PAD_L + i * BAR_SPACE + (BAR_SPACE - BAR_W) / 2

  const yTicks = [0, yMax * 0.25, yMax * 0.5, yMax * 0.75, yMax]

  return (
    <div className="relative" onMouseLeave={() => setTooltip(null)}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Token usage chart"
        style={{ display: 'block' }}
      >
        {/* Grid */}
        {yTicks.map((v, k) => (
          <g key={k}>
            <line
              x1={PAD_L} y1={toY(v)} x2={PAD_L + CW} y2={toY(v)}
              stroke={gridColor} strokeWidth="1" strokeDasharray="3 3"
            />
            <text
              x={PAD_L - 5} y={toY(v)}
              textAnchor="end" dominantBaseline="middle"
              fontSize="9" fill={textColor}
            >{fmtK(v)}</text>
          </g>
        ))}

        {/* Stacked bars */}
        {data.map((d, i) => {
          const total  = d.input + d.output
          const yBase  = toY(0)
          const yInputTop  = toY(d.input)
          const yOutputTop = toY(total)
          const inputH  = yBase - yInputTop
          const outputH = yInputTop - yOutputTop

          return (
            <g
              key={i}
              className="cursor-pointer"
              onMouseEnter={e => {
                const svgEl = (e.currentTarget as SVGGElement).ownerSVGElement!
                const rect = svgEl.getBoundingClientRect()
                const scaleX = rect.width / W
                const scaleY = rect.height / H
                setTooltip({
                  x: (barX(i) + BAR_W / 2) * scaleX + rect.left,
                  y: yOutputTop * scaleY + rect.top,
                  d,
                })
              }}
            >
              {/* Input (blue, bottom) */}
              <rect
                x={barX(i)} y={yInputTop}
                width={BAR_W} height={Math.max(inputH, 0)}
                fill="#3B82F6" rx="2"
              />
              {/* Output (orange, top) */}
              <rect
                x={barX(i)} y={yOutputTop}
                width={BAR_W} height={Math.max(outputH, 0)}
                fill="#F97316" rx="2"
              />
            </g>
          )
        })}

        {/* X-axis labels */}
        {data.map((d, i) => (
          <text
            key={i}
            x={barX(i) + BAR_W / 2}
            y={PAD_T + CH + 16}
            textAnchor="middle" fontSize="10" fill={textColor}
          >{d.date}</text>
        ))}
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="fixed z-50 pointer-events-none px-3 py-2 rounded-lg bg-gray-900 dark:bg-gray-700 text-white text-xs shadow-lg border border-gray-700 dark:border-gray-600"
          style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}
        >
          <p className="font-semibold mb-1">{tooltip.d.date}</p>
          <p className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-blue-400 inline-block" />
            Input: <strong>{fmtK(tooltip.d.input)}</strong>
          </p>
          <p className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-orange-400 inline-block" />
            Output: <strong>{fmtK(tooltip.d.output)}</strong>
          </p>
          <p className="text-gray-300 mt-1">Total: {fmtK(tooltip.d.input + tooltip.d.output)}</p>
        </div>
      )}
    </div>
  )
}
