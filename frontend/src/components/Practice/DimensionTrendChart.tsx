/**
 * 四维趋势（流利/词汇/语法/任务）轻量 SVG 多线图（无第三方依赖）。
 * 成长页诊断卡用：四维 0-4 分，逐作答时间升序展示。
 */

import type { DimensionPoint } from "@/client"
import { useI18n } from "@/lib/i18n"

const WIDTH = 560
const HEIGHT = 180
const PADDING = 30

const SERIES = [
  { key: "fluency", color: "#3b82f6" },
  { key: "vocabulary", color: "#8b5cf6" },
  { key: "grammar", color: "#10b981" },
  { key: "task", color: "#f59e0b" },
] as const

export function DimensionTrendChart({ points }: { points: DimensionPoint[] }) {
  const { t } = useI18n()
  const usable = points.filter((p) =>
    SERIES.some((s) => typeof p[s.key] === "number"),
  )
  if (usable.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        {t({
          zh: "再完成几次问答练习后，这里会出现四维评分趋势。",
          en: "Complete a few more Q&A rounds and your dimension trend will appear here.",
        })}
      </p>
    )
  }
  const span = 4 // 四维 0-4
  const step =
    usable.length > 1 ? (WIDTH - PADDING * 2) / (usable.length - 1) : 0
  const coords = usable.map((p, i) => {
    const x = PADDING + step * i
    return { x, point: p }
  })
  const seriesPaths = SERIES.map((s) => {
    const pts = coords.flatMap((c) => {
      const v = c.point[s.key]
      return typeof v === "number"
        ? [
            {
              x: c.x,
              y: HEIGHT - PADDING - (v / span) * (HEIGHT - PADDING * 2),
              date: c.point.date,
            },
          ]
        : []
    })
    if (pts.length === 0) return null
    const path =
      pts.length < 2
        ? null
        : pts
            .map(
              (p, i) =>
                `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`,
            )
            .join(" ")
    return { series: s, path, pts }
  })

  return (
    <div className="space-y-1">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full"
        role="img"
        aria-label={t({ zh: "四维评分趋势", en: "Dimension score trend" })}
      >
        {/* 网格线（0/1/2/3/4） */}
        {[0, 1, 2, 3, 4].map((v) => {
          const y = HEIGHT - PADDING - (v / span) * (HEIGHT - PADDING * 2)
          return (
            <g key={v}>
              <line
                x1={PADDING}
                x2={WIDTH - PADDING}
                y1={y}
                y2={y}
                stroke="currentColor"
                strokeOpacity={0.12}
                strokeDasharray="4 4"
              />
              <text
                x={PADDING - 6}
                y={y + 4}
                fontSize={10}
                textAnchor="end"
                fill="currentColor"
                opacity={0.55}
              >
                {v}
              </text>
            </g>
          )
        })}
        {seriesPaths.map((row) =>
          row === null || row.path === null ? null : (
            <path
              key={row.series.key}
              d={row.path}
              fill="none"
              stroke={row.series.color}
              strokeWidth={2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ),
        )}
        {/* 数据点（单点维度也显示圆点：仅 1 次作答时趋势不空白） */}
        {seriesPaths.map((row) =>
          row === null
            ? null
            : row.pts.map((p, i) => (
                <circle
                  key={`${row.series.key}-${i}`}
                  cx={p.x}
                  cy={p.y}
                  r={3}
                  fill={row.series.color}
                >
                  <title>{`${row.series.key}: ${p.date}`}</title>
                </circle>
              )),
        )}
        {/* 首末日期 */}
        {usable.length > 0 && (
          <>
            <text
              x={coords[0].x}
              y={HEIGHT - 8}
              fontSize={11}
              textAnchor="middle"
              fill="currentColor"
              opacity={0.6}
            >
              {coords[0].point.date.slice(5)}
            </text>
            {usable.length > 1 && (
              <text
                x={coords[coords.length - 1].x}
                y={HEIGHT - 8}
                fontSize={11}
                textAnchor="middle"
                fill="currentColor"
                opacity={0.6}
              >
                {coords[coords.length - 1].point.date.slice(5)}
              </text>
            )}
          </>
        )}
      </svg>
      <div className="flex flex-wrap gap-3">
        {SERIES.map((s) => (
          <span
            key={s.key}
            className="flex items-center gap-1 text-xs text-muted-foreground"
          >
            <span
              className="inline-block size-2.5 rounded-full"
              style={{ backgroundColor: s.color }}
            />
            {t({
              zh: s.key,
              en: s.key,
            })}
          </span>
        ))}
      </div>
    </div>
  )
}

export default DimensionTrendChart
