import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router"
import {
  ArrowRight,
  BookA,
  BookOpenCheck,
  CheckCircle2,
  Circle,
  Clock,
  ListChecks,
  RefreshCw,
  SpellCheck,
} from "lucide-react"
import { toast } from "sonner"
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { APP_NAME } from "@/config"
import { useStudentGuard } from "@/hooks/useStudentGuard"
import { loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN_FIRST_TRY, EXPLAIN_MASKED_WORDS, TERMS } from "@/lib/terms"

/** 任务进度 → 双语徽标（进度与逾期两维独立展示） */
const PROGRESS_LABEL: Record<string, { zh: string; en: string }> = {
  not_started: { zh: "未开始", en: "Not started" },
  in_progress: { zh: "进行中", en: "In progress" },
  completed: { zh: "已完成", en: "Completed" },
}

export const Route = createFileRoute("/vocab/$code/")({
  component: VocabHomePage,
  head: () => ({
    meta: [{ title: `${TERMS.vocabLearning.zh} / Vocabulary - ${APP_NAME}` }],
  }),
})

function VocabHomePage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/vocab/$code/" })
  const navigate = useNavigate({ from: "/vocab/$code/" })
  const queryClient = useQueryClient()
  const student = loadStudent(code)

  const todayQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["vocab", code, "today", student?.id],
    queryFn: () =>
      VocabularyService.readVocabToday({ code: code.toUpperCase() }),
    enabled: student !== null,
  })

  // 「再练一轮」：上一轮已完成后开新的复习轮（round_no=max+1），
  // 历史轮次与首轮任务成绩保持不变
  const newRound = useMutation({
    mutationFn: (assignmentId: string) =>
      VocabularyService.startVocabSession({
        code: code.toUpperCase(),
        requestBody: { assignment_id: assignmentId, round: "new" },
      }),
    onSuccess: (_data, assignmentId) => {
      void queryClient.invalidateQueries({ queryKey: ["vocab", code] })
      // 固定新开的任务 ID 进入练习，避免聚焦漂移到其他任务
      void navigate({
        to: "/vocab/$code/practice",
        params: { code },
        search: { assignment: assignmentId },
      })
    },
    onError: (error) => {
      if (error instanceof Error) {
        toast.error(
          t({
            zh: "暂时不能开始新一轮：任务可能已结束或已过截止时间。",
            en: "Can't start a new round: the task may have ended or passed its due time.",
          }),
        )
      }
    },
  })

  const wrongQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["vocab", code, "wrong-words", student?.id],
    queryFn: () =>
      VocabularyService.readWrongWords({ code: code.toUpperCase() }),
    enabled: student !== null,
    staleTime: 30_000,
  })

  // 身份失效（清库/课堂重建后 404）：清除本地身份，引导重新进入
  useStudentGuard(code, student, todayQuery)

  if (student === null) return null

  if (todayQuery.isPending) {
    return (
      <StudentShell active="vocab">
        <div role="status" className="space-y-6">
          <span className="sr-only">
            {t({ zh: "正在加载词汇任务…", en: "Loading vocabulary tasks…" })}
          </span>
          <Skeleton className="h-44 rounded-2xl" />
          <Skeleton className="h-64 rounded-2xl" />
        </div>
      </StudentShell>
    )
  }

  if (todayQuery.isError) {
    return (
      <StudentShell active="vocab">
        <Card className="items-center px-6 py-12 text-center">
          <BookA className="size-10 text-primary" />
          <div role="alert" className="space-y-2">
            <h1 className="text-xl font-semibold">
              {t({
                zh: "词汇任务暂时没有加载成功",
                en: "Vocabulary tasks failed to load",
              })}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t({
                zh: "请检查网络连接，再试一次。你的练习记录不会丢失。",
                en: "Check your connection and try again. Your records are safe.",
              })}
            </p>
          </div>
          <Button
            onClick={() => void todayQuery.refetch()}
            disabled={todayQuery.isFetching}
          >
            {t({ zh: "重新加载", en: "Reload" })}
          </Button>
        </Card>
      </StudentShell>
    )
  }

  const plan = todayQuery.data
  const assignment = plan.assignment ?? null
  const items = plan.items ?? []
  const total = items.length
  const answered = plan.answered_count ?? 0
  const correctFirst = plan.correct_first_count ?? 0
  const finished = assignment !== null && answered >= total && total > 0
  const accuracy =
    answered > 0 ? Math.round((correctFirst / answered) * 100) : null
  const wrongWords = wrongQuery.data?.items ?? []
  const taskRows = plan.assignments ?? []
  // 聚焦轮因截止/归档被关闭：不能再作答（历史仍可回看）
  const closedReason = plan.session_closed_reason ?? null

  return (
    <StudentShell active="vocab" wide>
      <div className="flex flex-col gap-7">
        <section className="rounded-3xl border border-primary/10 bg-secondary/40 p-6 sm:p-8">
          <p className="mb-2 flex items-center gap-2 text-[10px] font-semibold tracking-[0.2em] text-primary">
            <span className="h-px w-6 bg-primary/40" /> VOCABULARY
          </p>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            {t(TERMS.vocabLearning)}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {t({
              zh: "看中文释义，拼出英文单词；拼错的词会自动收进错词本。",
              en: "Read the Chinese meaning and spell the English word; misspelled words go to your Wrong Words book.",
            })}
          </p>
        </section>

        {/* 我的任务列表（多任务并存：进行中与已结束都在，可切换练习） */}
        {taskRows.length > 0 && (
          <section
            aria-label={t({ zh: "我的词汇任务", en: "My vocabulary tasks" })}
          >
            <p className="mb-2 text-xs font-medium text-muted-foreground">
              {t({
                zh: "我的任务（老师新发布的不会再结束旧任务）",
                en: "My tasks (new ones no longer end older tasks)",
              })}
            </p>
            <ul className="grid gap-2 md:grid-cols-2">
              {taskRows.map((row) => (
                <li key={row.assignment_id}>
                  <button
                    type="button"
                    onClick={() =>
                      void navigate({
                        to: "/vocab/$code/practice",
                        params: { code },
                        search: { assignment: row.assignment_id },
                      })
                    }
                    className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl border bg-card px-4 py-3.5 text-left transition-colors hover:border-primary/40"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {row.title}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {t({
                          zh: `${row.word_count} 词 · 首答 ${row.correct_first_count}/${row.word_count}`,
                          en: `${row.word_count} words · ${row.correct_first_count}/${row.word_count} first-try`,
                        })}
                        {(row.round_count ?? 0) > 1 &&
                          ` · ${t({
                            zh: `已练 ${row.round_count ?? 0} 轮`,
                            en: `${row.round_count ?? 0} rounds`,
                          })}`}
                        {row.due_at &&
                          ` · ${t({ zh: "截止", en: "Due" })} ${new Date(row.due_at).toLocaleDateString()}`}
                      </span>
                    </span>
                    {row.overdue && (
                      <Badge
                        variant="outline"
                        className="shrink-0 text-amber-600"
                      >
                        <Clock className="size-3" />
                        {t({ zh: "已逾期", en: "Overdue" })}
                      </Badge>
                    )}
                    <Badge
                      variant={
                        row.progress === "completed" ? "secondary" : "outline"
                      }
                      className={
                        row.progress === "completed"
                          ? "shrink-0 text-primary"
                          : "shrink-0"
                      }
                    >
                      {t(
                        PROGRESS_LABEL[row.progress ?? ""] ?? {
                          zh: row.progress ?? "",
                          en: row.progress ?? "",
                        },
                      )}
                    </Badge>
                    <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* 聚焦任务练习卡 */}
        {assignment === null ? (
          <Card>
            <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
              <div className="flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-xl bg-secondary text-primary">
                  <ListChecks className="size-5" />
                </span>
                <div>
                  <CardTitle className="text-base">
                    {t(TERMS.vocabTask)}
                  </CardTitle>
                  <CardDescription>
                    {t({
                      zh: "老师还没有发布词汇任务。",
                      en: "Your teacher hasn't published a vocabulary task yet.",
                    })}
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <p
                role="status"
                className="rounded-xl bg-secondary/50 p-4 text-sm leading-6 text-muted-foreground"
              >
                {t({
                  zh: "有新任务时这里会第一时间出现。可以先看看错词本，复习之前拼错的词。",
                  en: "New tasks will appear here first. Meanwhile, review the words you misspelled in Wrong Words.",
                })}
              </p>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
                  <SpellCheck className="size-5" />
                </span>
                <div className="min-w-0">
                  <CardTitle className="truncate text-base">
                    {assignment.title}
                    {finished && (
                      <Badge variant="secondary" className="ml-2 align-middle">
                        {t({ zh: "已完成", en: "Completed" })}
                      </Badge>
                    )}
                  </CardTitle>
                  <CardDescription>
                    {t({
                      zh: `${total} 个词 · 已答 ${answered} · 首答正确 ${correctFirst}`,
                      en: `${total} words · ${answered} answered · ${correctFirst} correct on first try`,
                    })}
                    <InfoHint label={t(EXPLAIN_FIRST_TRY)} />
                    {accuracy !== null &&
                      ` · ${t({ zh: "首答正确率", en: "first-try accuracy" })} ${accuracy}%`}
                  </CardDescription>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void todayQuery.refetch()}
                  disabled={todayQuery.isFetching}
                >
                  <RefreshCw
                    className={todayQuery.isFetching ? "animate-spin" : ""}
                  />
                  <span className="sr-only">
                    {t({ zh: "刷新", en: "Refresh" })}
                  </span>
                </Button>
                {closedReason ? (
                  <Badge variant="outline" className="shrink-0 text-amber-600">
                    <Clock className="size-3" />
                    {closedReason === "archived"
                      ? t({ zh: "老师已结束任务", en: "Ended by teacher" })
                      : t({ zh: "已过截止时间", en: "Past due" })}
                  </Badge>
                ) : finished ? (
                  <Button
                    onClick={() => newRound.mutate(assignment.id)}
                    disabled={newRound.isPending}
                  >
                    {newRound.isPending
                      ? t({ zh: "开新一轮…", en: "Starting…" })
                      : t({ zh: "再练一轮", en: "New round" })}
                    <ArrowRight />
                  </Button>
                ) : (
                  <Button
                    onClick={() =>
                      void navigate({
                        to: "/vocab/$code/practice",
                        params: { code },
                        search: { assignment: assignment.id },
                      })
                    }
                  >
                    {answered === 0
                      ? t({ zh: "开始练习", en: "Start practice" })
                      : t({ zh: "继续练习", en: "Continue practice" })}
                    <ArrowRight />
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-xs text-muted-foreground">
                {t(EXPLAIN_MASKED_WORDS)}
              </p>
              <div className="flex items-center gap-3">
                <div
                  role="progressbar"
                  aria-label={t({
                    zh: "词汇任务完成进度",
                    en: "Vocabulary task progress",
                  })}
                  aria-valuemin={0}
                  aria-valuemax={total || 1}
                  aria-valuenow={Math.min(answered, total)}
                  className="h-2 flex-1 overflow-hidden rounded-full bg-secondary"
                >
                  <div
                    className="h-full rounded-full bg-primary transition-all"
                    style={{
                      width: `${total === 0 ? 0 : Math.min((answered / total) * 100, 100).toFixed(0)}%`,
                    }}
                  />
                </div>
                <span className="text-[11px] text-muted-foreground">
                  {t({
                    zh: `${answered} / ${total} 已作答`,
                    en: `${answered} / ${total} answered`,
                  })}
                </span>
              </div>
              <ul className="grid gap-2 sm:grid-cols-2">
                {items.map((item) => (
                  <li
                    key={item.item_index}
                    className="flex items-center gap-2.5 rounded-xl border px-3 py-2.5"
                  >
                    {item.answered ? (
                      item.is_correct ? (
                        <CheckCircle2 className="size-4 shrink-0 text-primary" />
                      ) : (
                        <Circle className="size-4 shrink-0 text-muted-foreground" />
                      )
                    ) : (
                      <Circle className="size-4 shrink-0 text-border" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-sm">
                      {item.answered && item.headword ? (
                        <span className="font-semibold">{item.headword}</span>
                      ) : (
                        <span className="text-muted-foreground">?</span>
                      )}
                      <span className="ml-2 text-muted-foreground">
                        {item.meaning_zh}
                      </span>
                    </span>
                    {item.attempt_count && item.attempt_count > 1 ? (
                      <Badge variant="outline" className="shrink-0">
                        {t({
                          zh: `练 ${item.attempt_count} 次`,
                          en: `${item.attempt_count} tries`,
                        })}
                      </Badge>
                    ) : null}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        {/* 错词本 */}
        <Card>
          <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-secondary text-primary">
                <BookOpenCheck className="size-5" />
              </span>
              <div>
                <CardTitle className="text-base">
                  {t(TERMS.wrongWords)}{" "}
                  <span className="text-sm font-normal text-muted-foreground">
                    {wrongWords.length > 0 && `· ${wrongWords.length}`}
                  </span>
                </CardTitle>
                <CardDescription>
                  {t({
                    zh: "第一次没拼对的词都在这里，多看几眼就熟了。",
                    en: "Words you missed on the first try live here — a few looks and they're yours.",
                  })}
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="pb-0">
            {wrongQuery.isPending ? (
              <div role="status" className="pb-6 text-sm text-muted-foreground">
                {t({ zh: "正在加载错词本…", en: "Loading wrong words…" })}
              </div>
            ) : wrongWords.length === 0 ? (
              <p className="pb-6 text-sm text-muted-foreground">
                {t({
                  zh: "还没有拼错的词。继续保持！",
                  en: "No misspelled words yet. Keep it up!",
                })}
              </p>
            ) : (
              <>
                <p className="pb-3 text-xs text-muted-foreground sm:hidden">
                  {t({
                    zh: "横向滑动表格，可以查看完整错词。",
                    en: "Swipe the table sideways to see all words.",
                  })}
                </p>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t({ zh: "单词", en: "Word" })}</TableHead>
                      <TableHead>{t({ zh: "释义", en: "Meaning" })}</TableHead>
                      <TableHead>
                        {t({ zh: "拼错次数", en: "Missed" })}
                      </TableHead>
                      <TableHead>
                        {t({ zh: "最近拼错", en: "Last missed" })}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {wrongWords.map((word) => (
                      <TableRow key={word.word_id}>
                        <TableCell className="font-semibold">
                          {word.headword}
                          {word.part_of_speech && (
                            <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                              {word.part_of_speech}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {word.meaning_zh}
                        </TableCell>
                        <TableCell className="tabular-nums">
                          {word.wrong_count}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {word.last_wrong_at
                            ? new Date(word.last_wrong_at).toLocaleDateString()
                            : "–"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </>
            )}
          </CardContent>
        </Card>

        <p className="pb-4 text-center text-xs text-muted-foreground">
          {t({
            zh: "拼写给的是练习反馈，不是考试成绩；错词只用来帮你复习。",
            en: "Spelling results are practice feedback, not exam grades; wrong words only help you review.",
          })}
        </p>
      </div>
    </StudentShell>
  )
}
