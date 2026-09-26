/**
 * 轻量 SVG 折线图（无第三方依赖）：学生轨迹页用。
 * PRD US-09：口语参考分与词汇档两条线分开，不混一条曲线。
 */

interface TrailPoint {
  label: string // x 轴（日期）
  value: number | null
}

const WIDTH = 560
const HEIGHT = 160
const PADDING = 28

function buildPath(points: TrailPoint[], min: number, max: number) {
  const span = max - min || 1
  const usable = points.filter((p) => p.value !== null) as {
    label: string
    value: number
  }[]
  if (usable.length === 0) return null
  const step =
    usable.length > 1 ? (WIDTH - PADDING * 2) / (usable.length - 1) : 0
  const coords = usable.map((p, i) => {
    const x = PADDING + step * i
    const y =
      HEIGHT - PADDING - ((p.value - min) / span) * (HEIGHT - PADDING * 2)
    return { x, y, ...p }
  })
  const path = coords
    .map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`)
    .join(" ")
  return { path, coords }
}

function TrailChart({
  title,
  points,
  min,
  max,
  formatValue,
}: {
  title: string
  points: TrailPoint[]
  min: number
  max: number
  formatValue?: (value: number) => string
}) {
  const chart = buildPath(points, min, max)

  return (
    <div className="space-y-1">
      <p className="text-sm font-medium">{title}</p>
      {chart === null ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          暂无数据
        </p>
      ) : (
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="w-full"
          role="img"
          aria-label={title}
        >
          {/* 网格线 */}
          {[0, 0.5, 1].map((t) => {
            const y = HEIGHT - PADDING - t * (HEIGHT - PADDING * 2)
            return (
              <line
                key={t}
                x1={PADDING}
                x2={WIDTH - PADDING}
                y1={y}
                y2={y}
                stroke="currentColor"
                strokeOpacity={0.15}
                strokeDasharray="4 4"
              />
            )
          })}
          {/* 渐变填充（SpeakUp 成长页样式） */}
          <defs>
            <linearGradient id="trail-fill" x1="0" y1="0" x2="0" y2="1">
              <stop stopColor="currentColor" stopOpacity={0.25} />
              <stop offset="1" stopColor="currentColor" stopOpacity={0} />
            </linearGradient>
          </defs>
          {chart.coords.length > 1 && (
            <path
              d={`${chart.path} L${chart.coords[chart.coords.length - 1].x.toFixed(1)},${HEIGHT - PADDING} L${chart.coords[0].x.toFixed(1)},${HEIGHT - PADDING} Z`}
              fill="url(#trail-fill)"
              stroke="none"
            />
          )}
          <path
            d={chart.path}
            fill="none"
            stroke="currentColor"
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {chart.coords.map((c) => (
            <g key={c.label}>
              <circle cx={c.x} cy={c.y} r={3.5} fill="currentColor" />
              <title>
                {c.label}: {formatValue ? formatValue(c.value) : c.value}
              </title>
            </g>
          ))}
          {/* y 轴上下限标注 */}
          <text
            x={4}
            y={PADDING + 4}
            fontSize={11}
            fill="currentColor"
            opacity={0.6}
          >
            {formatValue ? formatValue(max) : max}
          </text>
          <text
            x={4}
            y={HEIGHT - PADDING}
            fontSize={11}
            fill="currentColor"
            opacity={0.6}
          >
            {formatValue ? formatValue(min) : min}
          </text>
          {/* 首末日期 */}
          {chart.coords.length > 0 && (
            <>
              <text
                x={chart.coords[0].x}
                y={HEIGHT - 6}
                fontSize={11}
                textAnchor="middle"
                fill="currentColor"
                opacity={0.6}
              >
                {chart.coords[0].label.slice(5)}
              </text>
              {chart.coords.length > 1 && (
                <text
                  x={chart.coords[chart.coords.length - 1].x}
                  y={HEIGHT - 6}
                  fontSize={11}
                  textAnchor="middle"
                  fill="currentColor"
                  opacity={0.6}
                >
                  {chart.coords[chart.coords.length - 1].label.slice(5)}
                </text>
              )}
            </>
          )}
        </svg>
      )}
    </div>
  )
}

export default TrailChart
