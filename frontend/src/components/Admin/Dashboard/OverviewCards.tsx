import type { DashboardOverview } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { type BiString, useI18n } from "@/lib/i18n"
import { EXPLAIN } from "@/lib/terms"

/** 单张速览卡：标题（带口径解释触点）+ 大数字。触控目标 ≥44px。 */
function StatCard({
  label,
  value,
  hint,
}: {
  label: string
  value: string | number
  hint?: BiString
}) {
  const { t } = useI18n()
  return (
    <Card className="py-4">
      <CardContent className="flex min-h-11 flex-col justify-center px-4">
        <p className="flex items-center gap-1 text-xs text-muted-foreground">
          {label}
          {hint ? <InfoHint label={t(hint)} /> : null}
        </p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      </CardContent>
    </Card>
  )
}

/** 成功率 = 完成/(完成+失败)，分母为零显示 —。 */
function successRate(done: number, failed: number): string {
  const total = done + failed
  if (total === 0) return "—"
  return `${Math.round((done / total) * 100)}%`
}

/** 速览卡两排：今日 + 所选区间（同一口径并排对照）。 */
function OverviewCards({
  overview,
  pending,
  rangeLabel,
}: {
  overview: DashboardOverview | undefined
  pending: boolean
  rangeLabel: string
}) {
  const { t } = useI18n()

  if (pending || !overview) {
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
    )
  }

  const groups: Array<{
    title: string
    cards: Array<{ label: string; value: string | number; hint?: BiString }>
  }> = [
    {
      title: t({ zh: "今日", en: "Today" }),
      cards: [
        {
          label: t({ zh: "活跃学生", en: "Active students" }),
          value: overview.today.active_students,
          hint: EXPLAIN.dashboard_active,
        },
        {
          label: t({ zh: "活跃课堂", en: "Active classrooms" }),
          value: overview.today.active_classrooms,
          hint: EXPLAIN.dashboard_active,
        },
        {
          label: t({ zh: "提交作答", en: "Attempts" }),
          value: overview.today.attempts,
          hint: EXPLAIN.dashboard_active,
        },
        {
          label: t({ zh: "评分成功率", en: "Scoring success" }),
          value: successRate(
            overview.today.scored_done,
            overview.today.scored_failed,
          ),
          hint: EXPLAIN.dashboard_success,
        },
        {
          label: t({ zh: "模考场次", en: "Exam sessions" }),
          value: overview.today.exam_sessions,
        },
        {
          label: t({ zh: "异常与失败", en: "Issues & failures" }),
          value: overview.today.runtime_issues + overview.today.scored_failed,
          hint: EXPLAIN.dashboard_issues,
        },
      ],
    },
    {
      title: rangeLabel,
      cards: [
        {
          label: t({ zh: "活跃学生", en: "Active students" }),
          value: overview.range.active_students,
          hint: EXPLAIN.dashboard_active,
        },
        {
          label: t({ zh: "活跃课堂", en: "Active classrooms" }),
          value: overview.range.active_classrooms,
          hint: EXPLAIN.dashboard_active,
        },
        {
          label: t({ zh: "提交作答", en: "Attempts" }),
          value: overview.range.attempts,
          hint: EXPLAIN.dashboard_active,
        },
        {
          label: t({ zh: "评分成功率", en: "Scoring success" }),
          value: successRate(
            overview.range.scored_done,
            overview.range.scored_failed,
          ),
          hint: EXPLAIN.dashboard_success,
        },
        {
          label: t({ zh: "模考场次", en: "Exam sessions" }),
          value: overview.range.exam_sessions,
        },
        {
          label: t({ zh: "异常与失败", en: "Issues & failures" }),
          value: overview.range.runtime_issues + overview.range.scored_failed,
          hint: EXPLAIN.dashboard_issues,
        },
      ],
    },
  ]

  return (
    <div className="space-y-3">
      {groups.map((group) => (
        <section key={group.title} aria-label={group.title}>
          <h3 className="mb-2 text-sm font-medium text-muted-foreground">
            {group.title}
          </h3>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {group.cards.map((card) => (
              <StatCard key={card.label} {...card} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

export default OverviewCards
