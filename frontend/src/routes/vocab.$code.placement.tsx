import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  Compass,
  History,
  Lightbulb,
  RotateCcw,
  XCircle,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import {
  ApiError,
  type PlacementAnswerResponse,
  type PlacementChoice,
  type PlacementQuestion,
  type PlacementResultPublic,
  type PlacementStartResponse,
  VocabularyService,
} from "@/client"
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
import { VocabReadonlyBanner } from "@/components/Vocabulary/VocabReadonlyBanner"
import { APP_NAME } from "@/config"
import { useModules } from "@/hooks/useModules"
import { useStudentGuard } from "@/hooks/useStudentGuard"
import { loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import { placementBandLabel, placementLimitationLabel } from "@/lib/placement"
import { formatDateTime } from "@/lib/time"

export const Route = createFileRoute("/vocab/$code/placement")({
  component: VocabPlacementPage,
  head: () => ({
    meta: [{ title: `测一测从哪开始 / Placement - ${APP_NAME}` }],
  }),
})

type Stage = "intro" | "answering" | "result"

function VocabPlacementPage() {
  const { t, lang } = useI18n()
  const { code } = useParams({ from: "/vocab/$code/placement" })
  const student = loadStudent(code)
  // 只读口径（#567 第 3 项）：模块非 active 时测分历史可回看，开始/重测隐藏。
  const { readonlyOf } = useModules()
  const readonly = readonlyOf("vocabulary") !== null

  const [stage, setStage] = useState<Stage>("intro")
  const [sessionId, setSessionId] = useState<string>("")
  const [question, setQuestion] = useState<PlacementQuestion | null>(null)
  const [answeredCount, setAnsweredCount] = useState(0)
  const [plannedTotal, setPlannedTotal] = useState(0)
  const [result, setResult] = useState<PlacementResultPublic | null>(null)
  const [feedback, setFeedback] = useState<{
    isCorrect: boolean
    correctHeadword: string
    meaningZh: string
  } | null>(null)
  const [showHistory, setShowHistory] = useState(false)

  const historyQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["vocab", code, "placement-history", student?.id],
    queryFn: () =>
      VocabularyService.placementHistory({ code: code.toUpperCase() }),
    enabled: student !== null,
    staleTime: 15_000,
  })

  useStudentGuard(code, student, historyQuery)

  const startMutation = useMutation({
    mutationFn: () =>
      VocabularyService.startPlacement({ code: code.toUpperCase() }),
    onSuccess: (data: PlacementStartResponse) => {
      setResult(null)
      setFeedback(null)
      setSessionId(data.session_id)
      setPlannedTotal(data.planned_total)
      setAnsweredCount(data.answered_count)
      if (data.result) {
        setResult(data.result)
        setStage("result")
      } else if (data.question) {
        setQuestion(data.question)
        setStage("answering")
      } else {
        setStage("intro")
      }
    },
    onError: (error) => {
      const detail =
        error instanceof ApiError
          ? (error.body as { detail?: string } | null)?.detail
          : null
      if (detail === "placement_insufficient_words") {
        toast.error(
          t({
            zh: "本班可练词库还凑不出一组四选一，暂时不能测。",
            en: "There aren't enough practiceable words for a quiz yet.",
          }),
        )
      } else {
        toast.error(
          t({
            zh: "暂时不能开始，请稍后再试。",
            en: "Can't start right now. Please try again later.",
          }),
        )
      }
    },
  })

  const answerMutation = useMutation({
    mutationFn: (choice: PlacementChoice) =>
      VocabularyService.answerPlacement({
        code: code.toUpperCase(),
        session_id: sessionId,
        placementAnswerRequest: {
          item_index: question?.item_index ?? 0,
          answer: choice.word_id,
        },
      }),
    onSuccess: (data: PlacementAnswerResponse) => {
      setAnsweredCount(data.answered_count)
      if (data.result) {
        setResult(data.result)
        setQuestion(null)
        setStage("result")
        void historyQuery.refetch()
        return
      }
      setFeedback({
        isCorrect: data.is_correct,
        correctHeadword: data.correct_headword,
        meaningZh: data.meaning_zh,
      })
      if (data.question) {
        setQuestion(data.question)
      }
    },
    onError: () => {
      toast.error(
        t({
          zh: "作答提交失败，请再点一次选项。",
          en: "Answer didn't submit. Tap an option again.",
        }),
      )
    },
  })

  const historyItems = historyQuery.data?.items ?? []

  function pickChoice(choice: PlacementChoice) {
    if (answerMutation.isPending) return
    answerMutation.mutate(choice)
  }

  function restart() {
    setQuestion(null)
    setFeedback(null)
    startMutation.mutate()
  }

  if (student === null) return null

  return (
    <StudentShell active="vocab" wide>
      <div className="flex flex-col gap-6">
        <Link
          to="/vocab/$code"
          params={{ code }}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-primary"
        >
          <ArrowLeft className="size-4" />
          {t({ zh: "返回词汇首页", en: "Back to Vocabulary" })}
        </Link>

        <VocabReadonlyBanner />

        {/* 说明 / 开始 */}
        {stage === "intro" && (
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
                  <Compass className="size-5" />
                </span>
                <div>
                  <CardTitle className="text-xl">
                    {t({
                      zh: "测一测从哪开始",
                      en: "Find your starting level",
                    })}
                  </CardTitle>
                  <CardDescription>
                    {t({
                      zh: "约 12 道四选一，根据作答自动调整难度；结果只给建议起点级别和推荐词库。",
                      en: "About 12 multiple-choice items, adaptive to your answers. You'll get a suggested starting level and word book.",
                    })}
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="rounded-2xl bg-secondary/50 p-4 text-sm leading-relaxed text-muted-foreground">
                {t({
                  zh: "这是粗分档建议，不是定级、不是考试分数、也不发认证；可以重测，结果仅你和老师可见作教学参考。",
                  en: "This is a rough placement guide — not a level certification, exam score, or certificate. You can retake it; results are for your teacher's reference only.",
                })}
              </p>
              <div className="flex flex-wrap items-center gap-3">
                {!readonly && (
                  <Button
                    onClick={() => startMutation.mutate()}
                    disabled={startMutation.isPending}
                  >
                    <Compass />
                    {startMutation.isPending
                      ? t({ zh: "准备中…", en: "Preparing…" })
                      : t({ zh: "开始测一测", en: "Start the quiz" })}
                  </Button>
                )}
                {historyItems.length > 0 && (
                  <Button
                    variant="outline"
                    onClick={() => setShowHistory((open) => !open)}
                  >
                    <History />
                    {t({ zh: "查看历史", en: "History" })}
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* 作答中 */}
        {stage === "answering" && question && (
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-base">
                    {t({
                      zh: "选择正确的释义",
                      en: "Choose the correct meaning",
                    })}
                  </CardTitle>
                  <CardDescription>
                    {t({
                      zh: `第 ${answeredCount + 1} / ${plannedTotal} 题`,
                      en: `Item ${answeredCount + 1} / ${plannedTotal}`,
                    })}
                  </CardDescription>
                </div>
                <Badge variant="outline" className="font-normal">
                  {t(placementBandLabel(question.band))}
                </Badge>
              </div>
              <div
                role="progressbar"
                aria-label={t({
                  zh: "作答进度",
                  en: "Progress",
                })}
                aria-valuemin={0}
                aria-valuemax={plannedTotal || 1}
                aria-valuenow={answeredCount}
                className="h-2 overflow-hidden rounded-full bg-secondary"
              >
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{
                    width: `${
                      plannedTotal === 0
                        ? 0
                        : Math.min((answeredCount / plannedTotal) * 100, 100)
                    }%`,
                  }}
                />
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="rounded-2xl border border-primary/15 bg-secondary/40 p-5 text-center">
                <p className="font-mono text-2xl font-semibold tracking-tight">
                  {question.headword}
                </p>
                {question.part_of_speech && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {question.part_of_speech}
                  </p>
                )}
              </div>

              {feedback && (
                <div
                  className={`flex items-start gap-2 rounded-2xl border p-3 text-sm ${
                    feedback.isCorrect
                      ? "border-primary/25 bg-primary/5"
                      : "border-destructive/25 bg-destructive/5"
                  }`}
                >
                  {feedback.isCorrect ? (
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                  ) : (
                    <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
                  )}
                  <span>
                    <span className="font-medium">
                      {feedback.isCorrect
                        ? t({ zh: "答对了", en: "Correct" })
                        : t({ zh: "答错了", en: "Missed" })}
                    </span>
                    <span className="ml-2 text-muted-foreground">
                      {feedback.correctHeadword} · {feedback.meaningZh}
                    </span>
                  </span>
                </div>
              )}

              <ul className="grid gap-2">
                {question.choices.map((choice) => (
                  <li key={choice.word_id}>
                    <button
                      type="button"
                      onClick={() => pickChoice(choice)}
                      disabled={answerMutation.isPending}
                      className="flex min-h-11 w-full items-center rounded-2xl border bg-card px-4 py-3 text-left text-sm transition-colors hover:border-primary/40 disabled:opacity-60"
                    >
                      {choice.meaning_zh}
                    </button>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        {/* 结果 */}
        {stage === "result" && result && (
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
                  <Lightbulb className="size-5" />
                </span>
                <div>
                  <CardTitle className="text-xl">
                    {t({ zh: "建议起点", en: "Suggested starting point" })}
                  </CardTitle>
                  <CardDescription>
                    {t({
                      zh: "粗分档建议，不是定级或考试分数",
                      en: "Rough placement guide — not a level or exam score",
                    })}
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl bg-secondary/50 p-4">
                  <p className="text-xs text-muted-foreground">
                    {t({ zh: "建议档位", en: "Suggested band" })}
                  </p>
                  <p className="mt-1 text-lg font-semibold">
                    {t(placementBandLabel(result.recommended_band))}
                  </p>
                  {result.recommended_level && (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {result.recommended_level}
                    </p>
                  )}
                </div>
                <div className="rounded-2xl bg-secondary/50 p-4">
                  <p className="text-xs text-muted-foreground">
                    {t({ zh: "推荐词库", en: "Recommended book" })}
                  </p>
                  <p className="mt-1 flex items-center gap-1.5 text-lg font-semibold">
                    <BookOpen className="size-4" />
                    {result.recommended_book_title ?? "–"}
                  </p>
                </div>
              </div>

              <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted-foreground">
                <dt>{t({ zh: "作答题数", en: "Items" })}</dt>
                <dd className="tabular-nums">
                  {result.answered_count} / {result.question_count}
                </dd>
                <dt>{t({ zh: "答对", en: "Correct" })}</dt>
                <dd className="tabular-nums">{result.correct_count}</dd>
              </dl>

              {placementLimitationLabel(result.limitation) && (
                <p className="rounded-2xl border border-amber-300/40 bg-amber-50 p-3 text-sm text-amber-700 dark:text-amber-300">
                  {t(placementLimitationLabel(result.limitation)!)}
                </p>
              )}

              <p className="text-xs leading-relaxed text-muted-foreground">
                {t({
                  zh: "这个结果只用来帮你选择从哪里开始练，不写入你的等级档案，也不影响任务难度。",
                  en: "This only helps you choose where to start; it doesn't change your level record or task difficulty.",
                })}
              </p>

              <div className="flex flex-wrap items-center gap-3">
                {!readonly && (
                  <Button onClick={restart} disabled={startMutation.isPending}>
                    <RotateCcw />
                    {t({ zh: "再测一次", en: "Retake" })}
                  </Button>
                )}
                <Button
                  variant="outline"
                  onClick={() => setShowHistory((open) => !open)}
                >
                  <History />
                  {t({ zh: "历史记录", en: "History" })}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* 历史记录 */}
        {(showHistory || stage === "result") && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t({ zh: "测分历史", en: "Placement history" })}
              </CardTitle>
              <CardDescription>
                {t({
                  zh: "每次测分都会保留，可重测；旧记录不会被覆盖。",
                  en: "Every attempt is kept and old records are never overwritten.",
                })}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {historyQuery.isPending ? (
                <div role="status" className="space-y-2">
                  <Skeleton className="h-12 rounded-xl" />
                  <Skeleton className="h-12 rounded-xl" />
                </div>
              ) : historyItems.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {t({
                    zh: "还没有测分记录。",
                    en: "No placement attempts yet.",
                  })}
                </p>
              ) : (
                <ul className="grid gap-2">
                  {historyItems.map((row) => (
                    <li
                      key={row.id}
                      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl border px-4 py-3"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="font-medium">
                          {t(placementBandLabel(row.recommended_band))}
                        </span>
                        {row.recommended_level && (
                          <span className="ml-2 text-xs text-muted-foreground">
                            {row.recommended_level}
                          </span>
                        )}
                        <span className="ml-2 text-xs text-muted-foreground">
                          {t({
                            zh: `${row.question_count} 题 · 答对 ${row.correct_count}`,
                            en: `${row.question_count} items · ${row.correct_count} correct`,
                          })}
                        </span>
                      </span>
                      {placementLimitationLabel(row.limitation) && (
                        <Badge variant="outline" className="font-normal">
                          {t({ zh: "素材有限", en: "Limited" })}
                        </Badge>
                      )}
                      <span className="text-xs text-muted-foreground tabular-nums">
                        {row.submitted_at
                          ? formatDateTime(row.submitted_at, lang)
                          : "–"}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </StudentShell>
  )
}
