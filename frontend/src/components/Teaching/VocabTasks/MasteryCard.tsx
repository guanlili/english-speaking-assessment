import { useQuery } from "@tanstack/react-query"
import { AlarmClock, Download } from "lucide-react"
import { useState } from "react"
import { VocabularyService } from "@/client"
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
import { downloadCsv } from "@/lib/csv"
import { localDateStamp } from "@/lib/dates"
import { type BiString, useI18n } from "@/lib/i18n"
import {
  FSRS_STATE_LABEL,
  MASTERY_BAND_LABEL,
  MASTERY_DEFAULT_WINDOW_DAYS,
  MASTERY_WINDOW_DAYS,
  type MasteryBand,
  masteryAccuracyText,
  masteryCsvTable,
} from "@/lib/vocabMastery"

/** 分段徽标配色：偏弱警示 / 中等中性 / 较稳主色 / 无数据弱化 */
const BAND_VARIANT: Record<
  MasteryBand,
  "destructive" | "secondary" | "default" | "outline"
> = {
  low: "destructive",
  mid: "secondary",
  high: "default",
  no_data: "outline",
}

/**
 * 班级掌握度卡：首答正确率分段 + FSRS 状态分布 + 到期未复习提示。
 *
 * 口径（与后端一致，文案反复强调）：这是复习安排信号，**不是考试分数、
 * 也不是能力等级**；只统计本班教师任务轮首答，自主练习/复习/分班测不混入；
 * 零作答标「暂无首答」，不折算 0%。
 */
export function MasteryCard({
  code,
  assignmentId,
}: {
  code: string
  assignmentId: string | null
}) {
  const { t } = useI18n()
  const [windowDays, setWindowDays] = useState<number>(
    MASTERY_DEFAULT_WINDOW_DAYS,
  )

  const masteryQuery = useQuery({
    queryKey: ["vocab-teacher", code, "mastery", assignmentId, windowDays],
    queryFn: () =>
      VocabularyService.readVocabMastery({
        code: code.toUpperCase(),
        assignment_id: assignmentId ?? undefined,
        window_days: windowDays,
      }),
  })
  const report = masteryQuery.data

  const exportCsv = () => {
    if (!report) return
    downloadCsv(
      masteryCsvTable(report, {
        headword: t({ zh: "单词", en: "Word" }),
        meaningZh: t({ zh: "释义", en: "Meaning" }),
        correctFirst: t({ zh: "首答正确", en: "First-try correct" }),
        answered: t({ zh: "已答", en: "Answered" }),
        accuracy: t({ zh: "首答正确率", en: "First-try accuracy" }),
        band: t({ zh: "分段", en: "Band" }),
        fsrsNew: t(FSRS_STATE_LABEL.new),
        fsrsLearning: t(FSRS_STATE_LABEL.learning),
        fsrsReview: t(FSRS_STATE_LABEL.review),
        due: t({ zh: "到期未复习", en: "Due" }),
        bandLow: t(MASTERY_BAND_LABEL.low),
        bandMid: t(MASTERY_BAND_LABEL.mid),
        bandHigh: t(MASTERY_BAND_LABEL.high),
        bandNoData: t(MASTERY_BAND_LABEL.no_data),
      }),
      t({
        zh: `课堂${code}-掌握度-${windowDays}天-${localDateStamp()}.csv`,
        en: `classroom-${code}-mastery-${windowDays}d-${localDateStamp()}.csv`,
      }),
    )
  }

  if (masteryQuery.isPending) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-72" />
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-20 rounded-2xl" />
          <Skeleton className="h-40 rounded-2xl" />
        </CardContent>
      </Card>
    )
  }

  const summaryCards: Array<{ label: BiString; value: string }> = report
    ? [
        {
          label: { zh: "班级首答正确率", en: "Class first-try accuracy" },
          value: masteryAccuracyText(report.accuracy_rate),
        },
        { label: MASTERY_BAND_LABEL.low, value: String(report.low_count ?? 0) },
        { label: MASTERY_BAND_LABEL.mid, value: String(report.mid_count ?? 0) },
        {
          label: MASTERY_BAND_LABEL.high,
          value: String(report.high_count ?? 0),
        },
        {
          label: MASTERY_BAND_LABEL.no_data,
          value: String(report.no_data_count ?? 0),
        },
      ]
    : []

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t({ zh: "班级掌握度", en: "Class mastery" })}
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {report?.scope === "assignment"
              ? t({ zh: "按当前任务", en: "Current task" })
              : t({ zh: "全部任务", en: "All tasks" })}
          </span>
        </CardTitle>
        <CardDescription>
          {t({
            zh: "按教师任务轮首答统计：<60% 偏弱、60–85% 中等、>85% 较稳；无首答不计 0%。掌握度只用于安排复习，不是考试分数，也不是能力等级。",
            en: "First answers from teacher tasks only: below 60% weak, 60–85% mid, above 85% steady; unanswered words are not scored 0%. This plans review only — it is not a test score or ability level.",
          })}
          <span className="mt-1 block sm:hidden">
            {t({
              zh: "横向滑动表格，可以查看完整数据。",
              en: "Swipe the table sideways to see all data.",
            })}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <label
            htmlFor="vocab-mastery-window"
            className="text-xs font-medium text-muted-foreground"
          >
            {t({ zh: "时间窗：", en: "Window:" })}
          </label>
          <select
            id="vocab-mastery-window"
            value={windowDays}
            onChange={(event) => setWindowDays(Number(event.target.value))}
            className="h-11 min-w-0 w-full max-w-full rounded-xl border border-input bg-card px-3 text-base text-foreground transition-colors hover:border-primary/35 sm:w-auto"
          >
            {MASTERY_WINDOW_DAYS.map((days) => (
              <option key={days} value={days}>
                {t({ zh: `近 ${days} 天`, en: `Last ${days} days` })}
              </option>
            ))}
          </select>
          <Button
            variant="outline"
            size="sm"
            className="min-h-11 ml-auto"
            disabled={!report}
            onClick={exportCsv}
          >
            <Download />
            {t({ zh: "导出掌握度", en: "Export mastery" })}
          </Button>
        </div>

        {report && (report.due_count ?? 0) > 0 && (
          <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200">
            <AlarmClock className="mt-0.5 size-4 shrink-0" />
            <span>
              {t({
                zh: `有 ${report.due_count ?? 0} 条复习条目已到期（按学生 × 词 × 能力维度计，不是去重词数），可优先安排复习。`,
                en: `${report.due_count ?? 0} review entries are due (counted per student × word × capability, not unique words); schedule review first.`,
              })}
            </span>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
          {summaryCards.map((card) => (
            <Card key={t(card.label)}>
              <CardContent className="py-4">
                <p className="text-xs text-muted-foreground">{t(card.label)}</p>
                <p className="mt-1 text-2xl font-bold tabular-nums">
                  {card.value}
                </p>
              </CardContent>
            </Card>
          ))}
          <Card>
            <CardContent className="py-4">
              <p className="text-xs text-muted-foreground">
                {t({ zh: "复习状态（条目）", en: "Review states (entries)" })}
              </p>
              <p className="mt-1 text-sm font-semibold tabular-nums">
                {report
                  ? `${report.fsrs_new ?? 0} · ${report.fsrs_learning ?? 0} · ${report.fsrs_review ?? 0}`
                  : "–"}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {t({
                  zh: "新词 · 学习中 · 待复习",
                  en: "New · Learning · Review",
                })}
              </p>
            </CardContent>
          </Card>
        </div>

        {(!report || (report.words ?? []).length === 0) && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t({
              zh: "该时间窗内暂无首答数据。",
              en: "No first-answer data in this window.",
            })}
          </p>
        )}

        {report && (report.words ?? []).length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t({ zh: "单词", en: "Word" })}</TableHead>
                <TableHead>{t({ zh: "释义", en: "Meaning" })}</TableHead>
                <TableHead>
                  {t({ zh: "首答正确/已答", en: "Correct/Answered" })}
                </TableHead>
                <TableHead>
                  {t({ zh: "首答正确率", en: "First-try accuracy" })}
                </TableHead>
                <TableHead>{t({ zh: "分段", en: "Band" })}</TableHead>
                <TableHead>
                  {t({ zh: "复习状态", en: "Review states" })}
                </TableHead>
                <TableHead>{t({ zh: "到期", en: "Due" })}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(report.words ?? []).map((row) => (
                <TableRow key={row.word_id}>
                  <TableCell className="font-semibold">
                    {row.headword}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {row.meaning_zh}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {row.correct_first_count}/{row.answered_count}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {masteryAccuracyText(row.accuracy_rate)}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        BAND_VARIANT[(row.band ?? "no_data") as MasteryBand]
                      }
                    >
                      {t(
                        MASTERY_BAND_LABEL[
                          (row.band ?? "no_data") as MasteryBand
                        ],
                      )}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs tabular-nums text-muted-foreground">
                    {t(FSRS_STATE_LABEL.new)} {row.fsrs_new ?? 0} ·{" "}
                    {t(FSRS_STATE_LABEL.learning)} {row.fsrs_learning ?? 0} ·{" "}
                    {t(FSRS_STATE_LABEL.review)} {row.fsrs_review ?? 0}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {(row.due_count ?? 0) > 0 ? (
                      <span className="font-semibold text-amber-600">
                        {row.due_count ?? 0}
                      </span>
                    ) : (
                      "–"
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
