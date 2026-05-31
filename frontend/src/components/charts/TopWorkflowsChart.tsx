import { useDarkMode } from '../../hooks/useDarkMode'
import type { WorkflowStat } from '../../types'

interface Props {
  data: WorkflowStat[]
  loading?: boolean
}

const W = 500
const H = 220
const PAD_L = 130   // room for workflow names
const PAD_R = 50    // room for count label
const PAD_T = 12
const PAD_B = 12
const CW = W - PAD_L - PAD_R

export default function TopWorkflowsChart({ data, loading = false }: Props) {
  const dark = useDarkMode()

  const textColor = dark ? '#9CA3AF' : '#6B7280'
  const subColor  = dark ? '#6B7280' : '#9CA3AF'

  if (loading) {
    return <div className="h-[220px] rounded-lg skeleton" aria-hidden="true" />
  }

  if (data.length === 0) return null

  const maxCount = Math.max(...data.map(d => d.count), 1)
  const n = data.length
  const rowH = (H - PAD_T - PAD_B) / n
  const BAR_H = Math.min(rowH * 0.5, 22)

  const toBarW = (count: number) => (count / maxCount) * CW

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Top workflows chart"
      style={{ display: 'block' }}
    >
      {data.map((d, i) => {
        const cy    = PAD_T + i * rowH + rowH / 2
        const barW  = toBarW(d.count)
        const pct   = d.successRate
        const barFill = pct >= 95 ? '#22C55E' : pct >= 85 ? '#3B82F6' : '#F97316'

        return (
          <g key={d.name}>
            {/* Name label */}
            <text
              x={PAD_L - 8} y={cy}
              textAnchor="end" dominantBaseline="middle"
              fontSize="11" fill={textColor}
              className="font-medium"
            >
              {d.name.length > 15 ? d.name.slice(0, 14) + '…' : d.name}
            </text>

            {/* Bar background track */}
            <rect
              x={PAD_L} y={cy - BAR_H / 2}
              width={CW} height={BAR_H}
              fill={dark ? '#374151' : '#E5E7EB'} rx="4"
            />

            {/* Filled bar */}
            <rect
              x={PAD_L} y={cy - BAR_H / 2}
              width={Math.max(barW, 4)} height={BAR_H}
              fill={barFill} rx="4"
            />

            {/* Count + success rate */}
            <text
              x={PAD_L + CW + 6} y={cy - 5}
              dominantBaseline="middle"
              fontSize="11" fill={textColor} fontWeight="600"
            >{d.count}</text>
            <text
              x={PAD_L + CW + 6} y={cy + 9}
              dominantBaseline="middle"
              fontSize="9" fill={subColor}
            >{pct}%</text>
          </g>
        )
      })}
    </svg>
  )
}
