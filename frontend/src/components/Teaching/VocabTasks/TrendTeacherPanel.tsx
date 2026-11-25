import { useMutation, useQuery } from "@tanstack/react-query"
import {
  Download,
  LineChart,
  RotateCcw,
  ShieldAlert,
  TrendingUp,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { VocabularyTrendPeriod } from "@/client"
import { ApiError, VocabularyService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { localDateStamp } from "@/lib/dates"
import { useI18n } from "@/lib/i18n"
import { VOCAB_PROMPT_META, vocabPromptMeta } from "@/lib/terms"
import { MASTERY_BAND_LABEL } from "@/lib/vocabMastery"
import {
  formatTrendRate,
  normalizeTrendRate,
  type TrendGranularity,
  type TrendPoint,
  trendBandShare,
  trendBandTotal,
  trendHasRate,
  trendPeriodLabel,
  trendPoints,
} from "@/lib/vocabTrend"

const PERIOD_OPTIONS = [12, 24] as const
const BAND_KEYS = ["low", "mid", "high", "no_data"] as const

/** 分段配色：偏弱警示 / 中等中性 / 较稳主色 / 无数据弱化 */
const BAND_BAR_CLASS: Record<(typeof BAND_KEYS)[number], string> = {
  low: "bg-destructive/80",
  mid: "bg-amber-400/80",
  high: "bg-primary/80",
  no_data: "bg-muted-foreground/20",
}

const CHART_WIDTH = 560
const CHART_HEIGHT = 160
const CHART_PADDING = 28

interface TrendFilters {
  granularity: TrendGranularity
  periods: number
  bookId: string
  promptType: string
}

/**
 * 教师端「趋势」面板（挂在 `/t/$code/vocab` 词汇 Tab）。
 *
 * - 只读跨任务 / 时间趋势：完成率、首答正确率、掌握度分段、到期未复习。
 * - 率值无数据为 `null`，界面显示 `–`，不折算 0%；缺失周期图表留空断口。
 * - 口径为教学参考，不是考试分数或能力认证；到期未复习按当前 FSRS 状态回算。
 */
export function TrendTeacherPanel({ code }: { code: string }) {
  const { t } = useI18n()
  const [filters, setFilters] = useState<TrendFilters>({
    granularity: "week",
    periods: 12,
    bookId: "",
    promptType: "",
  })

  const booksQuery = useQuery({
    queryKey: ["vocab", code, "trend-books"],
    queryFn: () => VocabularyService.listBooks(),
    staleTime: 30_000,
  })
  const books = (booksQuery.data ?? []).filter(
    (book) => book.status === "active",
  )

  const trendQuery = useQuery({
    queryKey: [
      "vocab",
      code,
      "trend",
      filters.granularity,
      filters.periods,
      filters.bookId,
      filters.promptType,
    ],
    queryFn: () =>
      VocabularyService.getVocabularyTrend({
        code: code.toUpperCase(),
        granularity: filters.granularity,
        periods: filters.periods,
        book_id: filters.bookId || null,
        prompt_type: filters.promptType || null,
      }),
    retry: false,
  })

  const items = trendQuery.data?.items ?? []
  const latest = items[items.length - 1] ?? null

  const csvMutation = useMutation({
    mutationFn: () =>
      VocabularyService.getVocabularyTrendCsv({
        code: code.toUpperCase(),
        granularity: filters.granularity,
        periods: filters.periods,
        book_id: filters.bookId || null,
        prompt_type: filters.promptType || null,
      }),
    onSuccess: (csv) => {
      const blob = new Blob([String(csv ?? "")], {
        type: "text/csv;charset=utf-8",
      })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = t({
        zh: `课堂${code}-词汇趋势-${filters.granularity}-${localDateStamp()}.csv`,
        en: `classroom-${code}-vocab-trend-${filters.granularity}-${localDateStamp()}.csv`,
      })
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    },
    onError: () =>
      toast.error(
        t({
          zh: "导出 CSV 失败，请稍后再试。",
          en: "CSV export failed. Please try again later.",
        }),
      ),
  })

  const errorStatus =
    trendQuery.error instanceof ApiError ? trendQuery.error.status : 0

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <TrendingUp className="size-5 text-primary" />
            {t({ zh: "学习趋势", en: "Learning trend" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "跨任务按周 / 月汇总完成率、首答正确率与掌握度分段；只读取作答记录，不改动学生档案。",
              en: "Completion, first-try accuracy and mastery bands across tasks by week or month. Answers are read-only; student records are never changed.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-xs text-muted-foreground">
                {t({ zh: "统计粒度", en: "Granularity" })}
              </span>
              <select
                value={filters.granularity}
                onChange={(event) =>
                  setFilters((prev) => ({
                    ...prev,
                    granularity: event.target.value as TrendGranularity,
                  }))
                }
                className="min-h-11 rounded-xl border bg-card px-3 text-base"
              >
                <option value="week">{t({ zh: "按周", en: "Weekly" })}</option>
                <option value="month">
                  {t({ zh: "按月", en: "Monthly" })}
                </option>
              </select>
            </label>

            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-xs text-muted-foreground">
                {t({ zh: "周期数", en: "Periods" })}
              </span>
              <select
                value={filters.periods}
                onChange={(event) =>
                  setFilters((prev) => ({
                    ...prev,
                    periods: Number(event.target.value),
                  }))
                }
                className="min-h-11 rounded-xl border bg-card px-3 text-base"
              >
                {PERIOD_OPTIONS.map((periods) => (
                  <option key={periods} value={periods}>
                    {t({
                      zh: `最近 ${periods} 个周期`,
                      en: `Last ${periods} periods`,
                    })}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-xs text-muted-foreground">
                {t({ zh: "词库", en: "Word book" })}
              </span>
              <select
                value={filters.bookId}
                onChange={(event) =>
                  setFilters((prev) => ({
                    ...prev,
                    bookId: event.target.value,
                  }))
                }
                className="min-h-11 rounded-xl border bg-card px-3 text-base"
              >
                <option value="">
                  {t({ zh: "全部词库", en: "All books" })}
                </option>
                {books.map((book) => (
                  <option key={book.id} value={book.id}>
                    {book.title}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-xs text-muted-foreground">
                {t({ zh: "题型", en: "Question type" })}
              </span>
              <select
                value={filters.promptType}
                onChange={(event) =>
                  setFilters((prev) => ({
                    ...prev,
                    promptType: event.target.value,
                  }))
                }
                className="min-h-11 rounded-xl border bg-card px-3 text-base"
              >
                <option value="">
                  {t({ zh: "全部题型", en: "All types" })}
                </option>
                {Object.keys(VOCAB_PROMPT_META).map((promptType) => (
                  <option key={promptType} value={promptType}>
                    {t(vocabPromptMeta(promptType).label)}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="min-h-11"
              onClick={() => void trendQuery.refetch()}
              disabled={trendQuery.isFetching}
            >
              <RotateCcw />
              {t({ zh: "刷新", en: "Refresh" })}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="min-h-11"
              onClick={() => csvMutation.mutate()}
              disabled={csvMutation.isPending || items.length === 0}
            >
              <Download />
              {csvMutation.isPending
                ? t({ zh: "导出中…", en: "Exporting…" })
                : t({ zh: "导出 CSV", en: "Export CSV" })}
            </Button>
            <Badge variant="secondary">
              {t({
                zh: "教学参考，不是考试分数 / 能力认证",
                en: "Teaching reference only — not a test score or ability certification",
              })}
            </Badge>
          </div>
        </CardContent>
      </Card>

      {trendQuery.isPending ? (
        <div className="space-y-4">
          <Skeleton className="h-24 rounded-2xl" />
          <Skeleton className="h-48 rounded-2xl" />
        </div>
      ) : errorStatus === 403 ? (
        <ErrorPanel
          title={t({
            zh: "你还不是这个课堂的授权教师，请让管理员在后台把你绑到这间课堂。",
            en: "You are not an owner teacher of this classroom yet. Ask an admin to link you to it in the admin console.",
          })}
          onRetry={() => void trendQuery.refetch()}
          retrying={trendQuery.isFetching}
        />
      ) : trendQuery.isError ? (
        <ErrorPanel
          title={
            errorStatus === 404
              ? t({
                  zh: "课堂不存在或已被移除。",
                  en: "The classroom does not exist or has been removed.",
                })
              : t({
                  zh: "趋势数据暂时没有加载成功，请检查网络后重试。",
                  en: "The trend data failed to load. Check your network and retry.",
                })
          }
          onRetry={() => void trendQuery.refetch()}
          retrying={trendQuery.isFetching}
        />
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            {t({ zh: "暂无可统计数据。", en: "No statistics available yet." })}
          </CardContent>
        </Card>
      ) : (
        <>
          <MetricCards latest={latest} t={t} />

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <LineChart className="size-4 text-primary" />
                {t({ zh: "完成率 / 首答正确率", en: "Completion / accuracy" })}
              </CardTitle>
              <CardDescription>
                {t({
                  zh: "率值为 0–100%；无目标或无首答的周期留空，不折算 0%。",
                  en: "Rates are 0–100%; periods with no targets or no first answers are left blank, not scored 0%.",
                })}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <TrendLineChart
                periods={items}
                granularity={filters.granularity}
              />
              <BandBars periods={items} granularity={filters.granularity} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-wrap items-center justify-between gap-2 space-y-0">
              <CardTitle className="text-base">
                {t({ zh: "周期明细", en: "Period details" })}
              </CardTitle>
              <span className="text-xs text-muted-foreground">
                <ShieldAlert className="mr-1 inline size-3.5" />
                {t({
                  zh: "到期未复习按当前 FSRS 状态回算，历史周期仅供参考。",
                  en: "Due entries are recomputed from the current FSRS state; past periods are reference only.",
                })}
              </span>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t({ zh: "周期", en: "Period" })}</TableHead>
                    <TableHead className="text-right">
                      {t({ zh: "目标数", en: "Targets" })}
                    </TableHead>
                    <TableHead className="text-right">
                      {t({ zh: "完成数", en: "Done" })}
                    </TableHead>
                    <TableHead className="text-right">
                      {t({ zh: "完成率", en: "Completion" })}
                    </TableHead>
                    <TableHead className="text-right">
                      {t({ zh: "首答数", en: "Answered" })}
                    </TableHead>
                    <TableHead className="text-right">
                      {t({ zh: "正确数", en: "Correct" })}
                    </TableHead>
                    <TableHead className="text-right">
                      {t({ zh: "正确率", en: "Accuracy" })}
                    </TableHead>
                    <TableHead className="text-right">
                      {t(MASTERY_BAND_LABEL.low)}
                    </TableHead>
                    <TableHead className="text-right">
                      {t(MASTERY_BAND_LABEL.mid)}
                    </TableHead>
                    <TableHead className="text-right">
                      {t(MASTERY_BAND_LABEL.high)}
                    </TableHead>
                    <TableHead className="text-right">
                      {t(MASTERY_BAND_LABEL.no_data)}
                    </TableHead>
                    <TableHead className="text-right">
                      {t({ zh: "到期未复习", en: "Due unreviewed" })}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((period) => (
                    <TableRow key={period.period_start}>
                      <TableCell className="tabular-nums">
                        {trendPeriodLabel(
                          period.period_start,
                          filters.granularity,
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {period.assigned_targets ?? 0}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {period.completed_targets ?? 0}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatTrendRate(period.completion_rate)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {period.first_answered ?? 0}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {period.first_correct ?? 0}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatTrendRate(period.first_accuracy)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {period.low_count ?? 0}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {period.mid_count ?? 0}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {period.high_count ?? 0}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {period.no_data_count ?? 0}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {period.due_unreviewed ?? 0}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

function ErrorPanel({
  title,
  onRetry,
  retrying,
}: {
  title: string
  onRetry: () => void
  retrying: boolean
}) {
  const { t } = useI18n()
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 text-muted-foreground">
      <p className="text-center">{title}</p>
      <Button variant="outline" onClick={onRetry} disabled={retrying}>
        <RotateCcw />
        {t({ zh: "重新加载", en: "Reload" })}
      </Button>
    </div>
  )
}

function MetricCards({
  latest,
  t,
}: {
  latest: VocabularyTrendPeriod | null
  t: (bi: { zh: string; en: string }) => string
}) {
  const metrics = [
    {
      label: { zh: "完成率（最近周期）", en: "Completion (latest)" },
      value: formatTrendRate(latest?.completion_rate),
    },
    {
      label: {
        zh: "首答正确率（最近周期）",
        en: "First-try accuracy (latest)",
      },
      value: formatTrendRate(latest?.first_accuracy),
    },
    {
      label: { zh: "到期未复习", en: "Due unreviewed" },
      value: String(latest?.due_unreviewed ?? 0),
    },
    {
      label: { zh: "首答参与（条目）", en: "First answers (entries)" },
      value: String(latest?.first_answered ?? 0),
    },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {metrics.map((metric) => (
        <Card key={t(metric.label)}>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">{t(metric.label)}</p>
            <p className="mt-1 text-2xl font-bold tabular-nums">
              {metric.value}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

/** 双系列 SVG 折线：完成率（主色）+ 首答正确率（警示色）；null 周期断口不连线。 */
function TrendLineChart({
  periods,
  granularity,
}: {
  periods: VocabularyTrendPeriod[]
  granularity: TrendGranularity
}) {
  const { t } = useI18n()
  const completionPoints = trendPoints(
    periods,
    (p) => p.completion_rate,
    granularity,
  )
  const accuracyPoints = trendPoints(
    periods,
    (p) => p.first_accuracy,
    granularity,
  )
  const hasCompletion = trendHasRate(periods, (p) => p.completion_rate)
  const hasAccuracy = trendHasRate(periods, (p) => p.first_accuracy)

  if (!hasCompletion && !hasAccuracy) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        {t({ zh: "暂无率值数据", en: "No rate data yet" })}
      </p>
    )
  }

  const step =
    periods.length > 1
      ? (CHART_WIDTH - CHART_PADDING * 2) / (periods.length - 1)
      : 0
  const xAt = (index: number) => CHART_PADDING + step * index
  const yAt = (value: number) => {
    const normalized = normalizeTrendRate(value) ?? 0
    return (
      CHART_HEIGHT -
      CHART_PADDING -
      normalized * (CHART_HEIGHT - CHART_PADDING * 2)
    )
  }

  const seriesPath = (points: TrendPoint[]) => {
    const segments: string[] = []
    let current: string[] = []
    points.forEach((point, index) => {
      if (point.value === null) {
        if (current.length > 0) {
          segments.push(current.join(" "))
          current = []
        }
        return
      }
      current.push(
        `${index === 0 || points[index - 1]?.value === null ? "M" : "L"}${xAt(index).toFixed(1)},${yAt(point.value).toFixed(1)}`,
      )
    })
    if (current.length > 0) segments.push(current.join(" "))
    return segments
  }

  const completionPaths = seriesPath(completionPoints)
  const accuracyPaths = seriesPath(accuracyPoints)

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-full bg-primary" />
          {t({ zh: "完成率", en: "Completion" })}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-full bg-destructive" />
          {t({ zh: "首答正确率", en: "First-try accuracy" })}
        </span>
      </div>
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
          className="w-full min-w-72"
          role="img"
          aria-label={t({
            zh: "完成率与首答正确率趋势图",
            en: "Completion and accuracy trend chart",
          })}
        >
          {[0, 0.5, 1].map((ratio) => {
            const y =
              CHART_HEIGHT -
              CHART_PADDING -
              ratio * (CHART_HEIGHT - CHART_PADDING * 2)
            return (
              <line
                key={ratio}
                x1={CHART_PADDING}
                x2={CHART_WIDTH - CHART_PADDING}
                y1={y}
                y2={y}
                stroke="currentColor"
                strokeOpacity={0.15}
                strokeDasharray="4 4"
              />
            )
          })}
          {completionPaths.map((path, index) => (
            <path
              key={`c-${index}`}
              d={path}
              fill="none"
              stroke="var(--primary)"
              strokeWidth={2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}
          {accuracyPaths.map((path, index) => (
            <path
              key={`a-${index}`}
              d={path}
              fill="none"
              stroke="var(--destructive)"
              strokeWidth={2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}
          {completionPoints.map((point, index) =>
            point.value === null ? null : (
              <circle
                key={`cp-${index}`}
                cx={xAt(index)}
                cy={yAt(point.value)}
                r={3}
                fill="var(--primary)"
              >
                <title>{`${point.label}: ${formatTrendRate(point.value)}`}</title>
              </circle>
            ),
          )}
          {accuracyPoints.map((point, index) =>
            point.value === null ? null : (
              <circle
                key={`ap-${index}`}
                cx={xAt(index)}
                cy={yAt(point.value)}
                r={3}
                fill="var(--destructive)"
              >
                <title>{`${point.label}: ${formatTrendRate(point.value)}`}</title>
              </circle>
            ),
          )}
          {completionPoints.length > 0 && (
            <>
              <text
                x={xAt(0)}
                y={CHART_HEIGHT - 6}
                fontSize={11}
                textAnchor="middle"
                fill="currentColor"
                opacity={0.6}
              >
                {completionPoints[0].label}
              </text>
              {completionPoints.length > 1 && (
                <text
                  x={xAt(completionPoints.length - 1)}
                  y={CHART_HEIGHT - 6}
                  fontSize={11}
                  textAnchor="middle"
                  fill="currentColor"
                  opacity={0.6}
                >
                  {completionPoints[completionPoints.length - 1].label}
                </text>
              )}
            </>
          )}
        </svg>
      </div>
    </div>
  )
}

/** 掌握度分段堆叠小柱：每周期一行，低 / 中 / 高 / 无数据按占比堆叠。 */
function BandBars({
  periods,
  granularity,
}: {
  periods: VocabularyTrendPeriod[]
  granularity: TrendGranularity
}) {
  const { t } = useI18n()
  const hasBands = periods.some((period) => trendBandTotal(period) > 0)
  if (!hasBands) return null

  return (
    <div className="mt-5 space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        {BAND_KEYS.map((key) => (
          <span key={key} className="flex items-center gap-1.5">
            <span
              className={`inline-block size-2.5 rounded-full ${BAND_BAR_CLASS[key]}`}
            />
            {t(MASTERY_BAND_LABEL[key])}
          </span>
        ))}
      </div>
      <div className="overflow-x-auto">
        <div className="min-w-72 space-y-2">
          {periods.map((period) => {
            const total = trendBandTotal(period)
            return (
              <div
                key={period.period_start}
                className="flex items-center gap-2"
              >
                <span className="w-16 shrink-0 text-xs tabular-nums text-muted-foreground">
                  {trendPeriodLabel(period.period_start, granularity)}
                </span>
                <div className="flex h-3 flex-1 overflow-hidden rounded-full bg-secondary">
                  {BAND_KEYS.map((key) => {
                    const share = trendBandShare(period, key)
                    if (share === null || share <= 0) return null
                    return (
                      <div
                        key={key}
                        className={`h-full ${BAND_BAR_CLASS[key]}`}
                        style={{ width: `${share * 100}%` }}
                      >
                        <title>
                          {`${t(MASTERY_BAND_LABEL[key])}: ${total > 0 ? Math.round(share * total) : 0}`}
                        </title>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
