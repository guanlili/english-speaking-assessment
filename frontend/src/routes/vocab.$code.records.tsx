import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import {
  ArrowLeft,
  ArrowRight,
  BrainCircuit,
  ChartLine,
  LibraryBig,
  RotateCcw,
  SpellCheck,
} from "lucide-react"
import { useMemo, useState } from "react"
import type { VocabularyStudentHistoryRow } from "@/client"
import { VocabularyService } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
import StudentShell from "@/components/Practice/StudentShell"
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
  OverallInsightDialog,
  SessionInsightDialog,
} from "@/components/Vocabulary/VocabAi"
import { VocabReadonlyBanner } from "@/components/Vocabulary/VocabReadonlyBanner"
import { APP_NAME } from "@/config"
import { useStudentGuard } from "@/hooks/useStudentGuard"
import { loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN_FIRST_TRY_ACCURACY, TERMS } from "@/lib/terms"
import { formatDate, formatDateTime } from "@/lib/time"
import { practiceRoundTitle } from "@/lib/vocab-review"

export const Route = createFileRoute("/vocab/$code/records")({
  component: VocabRecordsPage,
  head: () => ({
    meta: [{ title: `练习记录 / Practice Records - ${APP_NAME}` }],
  }),
})

const KIND_LABELS: Record<string, { zh: string; en: string }> = {
  task: { zh: "教师任务", en: "Teacher task" },
  self: { zh: "自主练习", en: "Self practice" },
  review: { zh: "错词复习", en: "Wrong-word review" },
  review_fsrs: { zh: "记忆复习", en: "Scheduled review" },
}

/** 趋势图展示的最多轮数（取最近已完成且已作答的轮次） */
const TREND_MAX_BARS = 12

function VocabRecordsPage() {
  const { t, lang } = useI18n()
  const { code } = useParams({ from: "/vocab/$code/records" })
  const navigate = useNavigate({ from: "/vocab/$code/records" })
  const student = loadStudent(code)
  const [overallOpen, setOverallOpen] = useState(false)
  const [insightSessionId, setInsightSessionId] = useState<string | null>(null)

  const historyQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["vocab", code, "student-history", student?.id],
    queryFn: () =>
      VocabularyService.readStudentHistory({
        code: code.toUpperCase(),
        limit: 50,
      }),
    enabled: student !== null,
  })

  useStudentGuard(code, student, historyQuery)

  const reviewStatsQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["vocab", code, "review-stats", student?.id],
    queryFn: () =>
      VocabularyService.readReviewStats({ code: code.toUpperCase() }),
    enabled: student !== null,
  })

  const rows = historyQuery.data?.items ?? []
  const reviewStats = reviewStatsQuery.data ?? null

  // 基础正确率趋势：最近已作答轮次（时间正序），零作答轮不进趋势
  const trend = useMemo(() => {
    return rows
      .filter((row) => (row.answered_count ?? 0) > 0)
      .slice(0, TREND_MAX_BARS)
      .reverse()
      .map((row) => ({
        key: row.session_id,
        label: accuracyLabel(row),
        ratio: (row.correct_first_count ?? 0) / (row.answered_count ?? 1),
        date: row.submitted_at ?? row.started_at,
        kind: row.kind,
      }))
  }, [rows])

  if (student === null) return null

  const detailTo = (row: VocabularyStudentHistoryRow) => {
    if (row.kind === "task" && row.assignment_id) {
      return {
        to: "/vocab/$code/practice",
        params: { code },
        search: {
          assignment: row.assignment_id,
          ...(row.round_no ? { round: String(row.round_no) } : {}),
        },
      } as const
    }
    return {
      to: "/vocab/$code/self",
      params: { code },
      search: { session: row.session_id },
    } as const
  }

  return (
    <StudentShell active="vocab" wide>
      <VocabReadonlyBanner />
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/vocab/$code" params={{ code }}>
              <ArrowLeft />
              {t({ zh: "返回词汇学习", en: "Back to Vocabulary" })}
            </Link>
          </Button>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link to="/vocab/$code/books" params={{ code }}>
                <LibraryBig />
                {t({ zh: "去词库挑词", en: "Browse Word Books" })}
              </Link>
            </Button>
            <Button size="sm" onClick={() => setOverallOpen(true)}>
              {t(TERMS.aiOverallInsight)}
            </Button>
          </div>
        </div>

        <section className="rounded-3xl border border-primary/10 bg-secondary/40 p-6 sm:p-8">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            {t(TERMS.practiceRecords)}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {t({
              zh: "教师任务、自主练习与错词复习分开记录；正确率只反映首答，不是考试成绩。",
              en: "Teacher tasks, self practice and wrong-word reviews are kept separate. Accuracy reflects first tries only — not exam grades.",
            })}
          </p>
        </section>

        {/* 复习档案真实计数（不估算留存率 / 掌握等级） */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <BrainCircuit className="size-4 text-primary" />
              {t({ zh: "复习档案", en: "Review Archive" })}
              <InfoHint
                label={t({
                  zh: "只统计真实复习次数与状态分布，不预测记忆留存率或掌握等级。",
                  en: "Real review counts and state distribution only — no retention forecast or mastery level.",
                })}
              />
            </CardTitle>
            <CardDescription>
              {t({
                zh: "认读（选择）与拼写（输入）分别记录；状态跟随账号跨班保留。",
                en: "Recognition and spelling are tracked separately; state follows your account across classes.",
              })}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(
                [
                  {
                    label: { zh: "档案条目", en: "Tracked" },
                    value: reviewStats?.tracked_count ?? 0,
                  },
                  {
                    label: { zh: "已到期", en: "Due" },
                    value: reviewStats?.due_count ?? 0,
                  },
                  {
                    label: { zh: "今日已复习", en: "Reviewed today" },
                    value: reviewStats?.reviewed_today_count ?? 0,
                  },
                  {
                    label: { zh: "学习中", en: "Learning" },
                    value: reviewStats?.learning_count ?? 0,
                  },
                  {
                    label: { zh: "长期记忆", en: "Established" },
                    value: reviewStats?.review_count ?? 0,
                  },
                  {
                    label: { zh: "认读", en: "Recognition" },
                    value: reviewStats?.recognition_count ?? 0,
                  },
                  {
                    label: { zh: "拼写", en: "Spelling" },
                    value: reviewStats?.spelling_count ?? 0,
                  },
                ] as const
              ).map((stat) => (
                <div
                  key={stat.label.en}
                  className="rounded-2xl bg-secondary/50 px-4 py-3"
                >
                  <dt className="text-xs text-muted-foreground">
                    {t(stat.label)}
                  </dt>
                  <dd className="mt-1 text-lg font-semibold tabular-nums">
                    {stat.value}
                  </dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>

        {/* 基础正确率趋势（最近已作答轮次） */}
        {trend.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ChartLine className="size-4 text-primary" />
                {t({ zh: "首答正确率趋势", en: "First-try accuracy trend" })}
                <InfoHint label={t(EXPLAIN_FIRST_TRY_ACCURACY)} />
              </CardTitle>
              <CardDescription>
                {t({
                  zh: `最近 ${trend.length} 个已作答轮次；零作答的轮次不进趋势图。`,
                  en: `Your last ${trend.length} rounds with answers; rounds without answers are not plotted.`,
                })}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-2">
                {trend.map((bar) => (
                  <li key={bar.key} className="flex items-center gap-3">
                    <span className="w-24 shrink-0 text-xs text-muted-foreground sm:w-32">
                      {bar.date ? formatDate(bar.date, lang) : "–"}
                    </span>
                    <div
                      role="img"
                      aria-label={t({
                        zh: `首答正确率 ${bar.label}`,
                        en: `First-try accuracy ${bar.label}`,
                      })}
                      className="h-5 min-w-0 flex-1 overflow-hidden rounded-full bg-secondary"
                    >
                      <div
                        className={`h-full rounded-full ${
                          bar.kind === "task"
                            ? "bg-primary"
                            : bar.kind === "review"
                              ? "bg-amber-500"
                              : bar.kind === "review_fsrs"
                                ? "bg-emerald-500"
                                : "bg-sky-500"
                        }`}
                        style={{
                          width: `${Math.max(Math.round(bar.ratio * 100), 4)}%`,
                        }}
                      />
                    </div>
                    <span className="w-12 shrink-0 text-right text-xs font-medium tabular-nums">
                      {bar.label}
                    </span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        {/* 历史列表 */}
        {historyQuery.isPending ? (
          <div role="status" className="space-y-3">
            <span className="sr-only">
              {t({ zh: "正在加载练习记录…", en: "Loading records…" })}
            </span>
            <Skeleton className="h-16 rounded-2xl" />
            <Skeleton className="h-16 rounded-2xl" />
          </div>
        ) : historyQuery.isError ? (
          <Card className="items-center px-6 py-10 text-center">
            <p role="alert" className="text-sm text-muted-foreground">
              {t({
                zh: "练习记录暂时没有加载成功，请重试。",
                en: "Records failed to load — please retry.",
              })}
            </p>
            <Button
              className="mt-4"
              onClick={() => void historyQuery.refetch()}
              disabled={historyQuery.isFetching}
            >
              {t({ zh: "重新加载", en: "Reload" })}
            </Button>
          </Card>
        ) : rows.length === 0 ? (
          <Card className="items-center px-6 py-10 text-center">
            <SpellCheck className="size-8 text-muted-foreground" />
            <p className="mt-3 text-sm text-muted-foreground">
              {t({
                zh: "还没有练习记录。开始一轮后这里会出现。",
                en: "No practice records yet — they'll appear here after your first round.",
              })}
            </p>
          </Card>
        ) : (
          <ul className="grid gap-2">
            {rows.map((row) => (
              <li key={row.session_id}>
                <button
                  type="button"
                  onClick={() => void navigate(detailTo(row))}
                  className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl border bg-card px-4 py-3.5 text-left transition-colors hover:border-primary/40"
                >
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium">
                        {t(practiceRoundTitle(row.kind, row.title))}
                      </span>
                      {row.kind === "review" && (
                        <RotateCcw className="size-3.5 shrink-0 text-muted-foreground" />
                      )}
                    </span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {t({
                        zh: `首答 ${row.correct_first_count ?? 0}/${row.answered_count ?? 0} · 共 ${row.total_count ?? 0} 题`,
                        en: `${row.correct_first_count ?? 0}/${row.answered_count ?? 0} first-try · ${row.total_count ?? 0} items`,
                      })}
                      {row.round_no
                        ? ` · ${t({ zh: `第 ${row.round_no} 轮`, en: `Round ${row.round_no}` })}`
                        : ""}
                      {` · ${
                        row.started_at
                          ? formatDateTime(row.started_at, lang)
                          : "–"
                      }`}
                    </span>
                  </span>
                  <Badge
                    variant="outline"
                    className="shrink-0 text-muted-foreground"
                  >
                    {t(KIND_LABELS[row.kind] ?? { zh: row.kind, en: row.kind })}
                  </Badge>
                  <Badge
                    variant={
                      row.status === "submitted" ? "secondary" : "outline"
                    }
                    className={
                      row.status === "submitted"
                        ? "shrink-0 text-primary"
                        : "shrink-0"
                    }
                  >
                    {row.status === "submitted"
                      ? row.end_reason === "timeout"
                        ? t(TERMS.quizTimedOut)
                        : row.masked
                          ? t(TERMS.quizSubmitted)
                          : t({ zh: "已完成", en: "Completed" })
                      : t({ zh: "进行中", en: "In progress" })}
                  </Badge>
                  <span className="flex shrink-0 items-center gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={(event) => {
                        event.stopPropagation()
                        setInsightSessionId(row.session_id)
                      }}
                    >
                      {t(TERMS.aiSessionInsight)}
                    </Button>
                    <ArrowRight className="size-4 text-muted-foreground" />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        <p className="pb-4 text-center text-xs text-muted-foreground">
          {t({
            zh: "这里只汇总结数，不画能力曲线；首答正确率的分母是已答题数。",
            en: "Counts only here — no ability curve. First-try accuracy divides by answered items.",
          })}
        </p>

        <OverallInsightDialog
          code={code}
          open={overallOpen}
          onClose={() => setOverallOpen(false)}
        />
        <SessionInsightDialog
          code={code}
          sessionId={insightSessionId}
          open={insightSessionId !== null}
          onClose={() => setInsightSessionId(null)}
        />
      </div>
    </StudentShell>
  )
}

function accuracyLabel(row: VocabularyStudentHistoryRow): string {
  // 首答正确率 = 首答正确 / 已答（分母不是总题数；零作答显示未作答）
  const answered = row.answered_count ?? 0
  if (answered <= 0) return "–"
  return `${Math.round(((row.correct_first_count ?? 0) / answered) * 100)}%`
}
