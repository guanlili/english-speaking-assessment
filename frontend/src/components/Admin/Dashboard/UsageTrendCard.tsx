import type { DashboardDailyPoint } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
import TrailChart from "@/components/Practice/TrailChart"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { type BiString, useI18n } from "@/lib/i18n"
import { EXPLAIN, ITEM_TYPE_LABELS } from "@/lib/terms"

/** 趋势图卡片：作答量 / 活跃学生 / 分数三条线（复用轻量 SVG TrailChart）。 */
function UsageTrendCard({ points }: { points: DashboardDailyPoint[] }) {
  const { t } = useI18n()

  const total = points.reduce((sum, p) => sum + p.attempts, 0)
  const peak = points.reduce((m, p) => Math.max(m, p.attempts), 0)
  const chart = (select: (p: DashboardDailyPoint) => number | null) =>
    points.map((p) => ({ label: p.date.slice(5), value: select(p) }))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          {t({ zh: "使用趋势", en: "Usage trend" })}
          <InfoHint label={t(EXPLAIN.dashboard_active)} />
        </CardTitle>
        <CardDescription>
          {t({
            zh: `区间内共 ${total} 次提交，单日峰值 ${peak} 次。`,
            en: `${total} attempts in range, daily peak ${peak}.`,
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div>
          <p className="mb-1 text-sm font-medium">
            {t({ zh: "每日提交作答数", en: "Attempts per day" })}
          </p>
          <TrailChart
            title=""
            points={chart((p) => p.attempts)}
            min={0}
            max={Math.max(peak, 5)}
          />
        </div>
        <div>
          <p className="mb-1 text-sm font-medium">
            {t({ zh: "每日活跃学生", en: "Active students per day" })}
          </p>
          <TrailChart
            title=""
            points={chart((p) => p.active_students)}
            min={0}
            max={Math.max(...points.map((p) => p.active_students), 5)}
          />
        </div>
        <div className="grid gap-5 lg:grid-cols-2">
          <div>
            <p className="mb-1 flex items-center gap-1 text-sm font-medium">
              {t({ zh: "问答均分", en: "Q&A average" })}
              <InfoHint label={t(EXPLAIN.dashboard_score)} />
            </p>
            <TrailChart
              title=""
              points={chart((p) => p.question_avg)}
              min={0}
              max={100}
            />
          </div>
          <div>
            <p className="mb-1 flex items-center gap-1 text-sm font-medium">
              {t({ zh: "跟读完整度均分", en: "Read-aloud completeness" })}
              <InfoHint label={t(EXPLAIN.dashboard_score)} />
            </p>
            <TrailChart
              title=""
              points={chart((p) => p.repeat_completeness_avg)}
              min={0}
              max={100}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

/** 题型分布：CSS 宽度条，无第三方图表依赖。 */
function ItemDistributionCard({
  distribution,
}: {
  distribution: Record<string, number>
}) {
  const { t } = useI18n()
  const entries = (["passage", "repeat", "question"] as const).map((key) => ({
    key,
    label: t(ITEM_TYPE_LABELS[key] as BiString),
    count: distribution[key] ?? 0,
  }))
  const total = entries.reduce((s, e) => s + e.count, 0)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t({ zh: "题型分布", en: "Item type mix" })}
        </CardTitle>
        <CardDescription>
          {t({
            zh: "所选区间内各题型的提交次数占比。",
            en: "Share of submissions by item type in range.",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {total === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            {t({ zh: "暂无数据", en: "No data yet" })}
          </p>
        ) : (
          entries.map((e) => (
            <div key={e.key} className="space-y-1">
              <div className="flex items-center justify-between text-sm">
                <span>{e.label}</span>
                <span className="tabular-nums text-muted-foreground">
                  {e.count}（{Math.round((e.count / total) * 100)}%）
                </span>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${(e.count / total) * 100}%` }}
                />
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  )
}

export { ItemDistributionCard, UsageTrendCard }
