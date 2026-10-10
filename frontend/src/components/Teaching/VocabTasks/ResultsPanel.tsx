import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Archive,
  CheckCircle2,
  CircleDashed,
  Download,
  RefreshCw,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import type { VocabularyStudentResultRow } from "@/client"
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
import { type BiString, useI18n } from "@/lib/i18n"
import { EXPLAIN_QUIZ_TAB_SWITCH, TERMS } from "@/lib/terms"
import { formatTime } from "@/lib/time"
import { QuizAnswerSheetDialog } from "./QuizAnswerSheetDialog"
import { RoundSelector } from "./RoundSelector"

/** 学生完成状态 → 双语标签 */
const STUDENT_STATUS: Record<string, BiString> = {
  completed: { zh: "已完成", en: "Completed" },
  in_progress: { zh: "进行中", en: "In progress" },
  not_started: { zh: "未开始", en: "Not started" },
}

/** 结果面板：完成统计 + 学生明细 + 逐词错误分布 */
export function ResultsPanel({
  code,
  assignments,
  selectedAssignmentId,
  onSelectAssignment,
}: {
  code: string
  assignments: Array<{
    id: string
    version_no: number
    title: string
    status: string
    word_count: number
  }>
  selectedAssignmentId: string | null
  onSelectAssignment: (id: string | null) => void
}) {
  const { t, lang } = useI18n()
  const queryClient = useQueryClient()
  // 查看哪一期：null = 当前进行中；归档/重发后可切换历史期数按快照回看
  const resultsQuery = useQuery({
    queryKey: ["vocab-teacher", code, "results", selectedAssignmentId],
    queryFn: () =>
      VocabularyService.readVocabResults({
        code: code.toUpperCase(),
        assignmentId: selectedAssignmentId ?? undefined,
      }),
    // 进行中的任务才轮询；历史期数是归档快照不可变，null(无任务) 由指派后失效刷新
    refetchInterval: (query) =>
      query.state.data?.assignment?.status === "active" ? 20_000 : false,
  })
  const archive = useMutation({
    mutationFn: (assignmentId: string) =>
      VocabularyService.archiveVocabAssignment({
        code: code.toUpperCase(),
        assignmentId,
      }),
    onSuccess: () => {
      toast.success(t({ zh: "任务已结束。", en: "Task archived." }))
      queryClient.invalidateQueries({ queryKey: ["vocab-teacher", code] })
    },
  })

  const results = resultsQuery.data
  const assignment = results?.assignment ?? null
  const isQuiz = assignment?.mode === "quiz"
  const publishGrades = useMutation({
    mutationFn: (assignmentId: string) =>
      VocabularyService.publishQuizGrades({
        code: code.toUpperCase(),
        assignmentId,
      }),
    onSuccess: () => {
      toast.success(t({ zh: "成绩已公布。", en: "Grades published." }))
      void queryClient.invalidateQueries({
        queryKey: ["vocab-teacher", code, "results"],
      })
    },
  })
  const publishAnswers = useMutation({
    mutationFn: (assignmentId: string) =>
      VocabularyService.publishQuizAnswers({
        code: code.toUpperCase(),
        assignmentId,
      }),
    onSuccess: () => {
      toast.success(
        t({
          zh: "答案已公布，错词本开始收录。",
          en: "Answers published; wrong words now flow into student books.",
        }),
      )
      void queryClient.invalidateQueries({
        queryKey: ["vocab-teacher", code, "results"],
      })
    },
  })
  const grantRetake = useMutation({
    mutationFn: (payload: { assignmentId: string; studentId: string }) =>
      VocabularyService.grantQuizRetake({
        code: code.toUpperCase(),
        assignmentId: payload.assignmentId,
        studentId: payload.studentId,
      }),
    onSuccess: () => {
      toast.success(t({ zh: "已授权补考一次。", en: "One retake granted." }))
      void queryClient.invalidateQueries({
        queryKey: ["vocab-teacher", code, "results"],
      })
    },
  })
  // 答卷查看：按学生拉取（最新一份；可切轮次在对话框内）
  const [sheetStudent, setSheetStudent] =
    useState<VocabularyStudentResultRow | null>(null)
  const [sheetRoundNo, setSheetRoundNo] = useState<number | null>(null)
  // 没有当前任务但有历史期数（如刚结束最后一期）→ 默认选中最近一期，
  // 保证归档成绩始终能从选择器进入（hook 必须在条件 return 之前）
  useEffect(() => {
    if (
      !assignment &&
      selectedAssignmentId === null &&
      assignments.length > 0
    ) {
      onSelectAssignment(assignments[0].id)
    }
  }, [assignment, selectedAssignmentId, assignments, onSelectAssignment])
  const students = useMemo(
    () =>
      [...(results?.students ?? [])].sort((a, b) =>
        a.display_name.localeCompare(b.display_name, "zh-Hans-CN"),
      ),
    [results],
  )
  const words = results?.words ?? []

  const exportCsv = async () => {
    if (!results || !assignment) return
    if (isQuiz) {
      // 测验用服务端导出（固定名单 + 成绩/切屏/终结方式口径）
      const csv = await VocabularyService.exportQuizResults({
        code: code.toUpperCase(),
        assignmentId: assignment.id,
      })
      const blob = new Blob([csv as string], {
        type: "text/csv;charset=utf-8",
      })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = t({
        zh: `课堂${code}-词汇测验-v${assignment.version_no}.csv`,
        en: `classroom-${code}-vocab-quiz-v${assignment.version_no}.csv`,
      })
      anchor.click()
      URL.revokeObjectURL(url)
      return
    }
    const header = [
      t({ zh: "姓名", en: "Name" }),
      t({ zh: "区分码", en: "Suffix" }),
      t({ zh: "状态", en: "Status" }),
      t({ zh: "已答/总词数", en: "Answered/Total" }),
      t({ zh: "首答正确", en: "First-try correct" }),
      t({ zh: "首答正确率", en: "First-try accuracy" }),
      t({ zh: "各轮首答正确", en: "First-try correct per round" }),
    ]
    const rows = students.map((row) => [
      row.display_name,
      row.suffix ?? "",
      t(STUDENT_STATUS[row.status] ?? { zh: row.status, en: row.status }),
      `${row.answered_count}/${row.total_count}`,
      String(row.correct_first_count),
      row.answered_count > 0
        ? `${Math.round((row.correct_first_count / row.answered_count) * 100)}%`
        : "-",
      // 任务成绩锁定首轮；复习轮单独列出，不影响上列成绩
      (row.rounds ?? [])
        .map(
          (round) =>
            `R${round.round_no} ${round.correct_first_count}/${round.answered_count}`,
        )
        .join("; "),
    ])
    downloadCsv(
      [header, ...rows],
      t({
        zh: `课堂${code}-词汇任务-${new Date().toISOString().slice(0, 10)}.csv`,
        en: `classroom-${code}-vocabulary-${new Date().toISOString().slice(0, 10)}.csv`,
      }),
    )
  }

  if (resultsQuery.isPending) {
    return (
      <div role="status" className="space-y-4">
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    )
  }

  if (!assignment) {
    return (
      <div className="space-y-6">
        <RoundSelector
          assignments={assignments}
          selectedAssignmentId={selectedAssignmentId}
          onSelect={onSelectAssignment}
        />
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            {selectedAssignmentId === null
              ? t({
                  zh: "还没有词汇任务，先到「发布任务」安排一期。",
                  en: "No vocabulary tasks yet — assign one first.",
                })
              : t({
                  zh: "该期数没有结果数据。",
                  en: "No result data for this round.",
                })}
          </CardContent>
        </Card>
      </div>
    )
  }

  const target = results?.target_count ?? 0
  const completed = results?.completed_count ?? 0
  const inProgress = results?.in_progress_count ?? 0
  const notStarted = results?.not_started_count ?? 0
  const errorWords = words.filter((w) => w.error_count > 0)

  return (
    <div className="space-y-6">
      <div
        className={`grid grid-cols-2 gap-3 ${isQuiz ? "md:grid-cols-3 lg:grid-cols-6" : "md:grid-cols-4"}`}
      >
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "名单学生", en: "Roster" })}
            </p>
            <p className="mt-1 text-2xl font-bold">{target}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">
              {t(
                isQuiz
                  ? { zh: "已交卷", en: "Submitted" }
                  : { zh: "已完成", en: "Completed" },
              )}
            </p>
            <p className="mt-1 text-2xl font-bold text-primary">{completed}</p>
          </CardContent>
        </Card>
        {isQuiz && (
          <Card>
            <CardContent className="py-4">
              <p className="text-xs text-muted-foreground">
                {t({ zh: "超时结束", en: "Timed out" })}
              </p>
              <p className="mt-1 text-2xl font-bold text-amber-600">
                {results?.timed_out_count ?? 0}
              </p>
            </CardContent>
          </Card>
        )}
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "进行中", en: "In progress" })}
            </p>
            <p className="mt-1 text-2xl font-bold">{inProgress}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "未开始", en: "Not started" })}
            </p>
            <p className="mt-1 text-2xl font-bold text-muted-foreground">
              {notStarted}
            </p>
          </CardContent>
        </Card>
        {isQuiz && (
          <Card>
            <CardContent className="py-4">
              <p className="text-xs text-muted-foreground">
                {t({ zh: "平均分", en: "Average" })}
              </p>
              <p className="mt-1 text-2xl font-bold">
                {results?.avg_score ?? "–"}
              </p>
            </CardContent>
          </Card>
        )}
        {isQuiz && (
          <Card>
            <CardContent className="py-4">
              <p className="text-xs text-muted-foreground">
                {t({ zh: "及格", en: "Passed" })}
              </p>
              <p className="mt-1 text-2xl font-bold text-primary">
                {results?.passed_count ?? 0}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  /
                  {t({
                    zh: `线 ${results?.pass_line ?? 60}`,
                    en: `of ${results?.pass_line ?? 60}`,
                  })}
                </span>
              </p>
            </CardContent>
          </Card>
        )}
      </div>

      <Card className="border-primary/20 bg-secondary/30">
        <CardContent className="flex flex-wrap items-center gap-3 py-4">
          <div className="mr-auto min-w-48">
            <p className="text-sm font-semibold">
              {t({
                zh: `完成率 ${target > 0 ? Math.round((completed / target) * 100) : 0}%`,
                en: `Completion ${target > 0 ? Math.round((completed / target) * 100) : 0}%`,
              })}
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {t({
                  zh: "（分母 = 发布时的名单，后加入的学生不计入）",
                  en: "(denominator = roster fixed at publish time)",
                })}
              </span>
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t(
                isQuiz
                  ? {
                      zh: "成绩 = 首答正确 ÷ 总题数（未答按 0 分计入）；有补考取最好成绩；切屏仅记录供参考。",
                      en: "Score = first-try correct ÷ total (unanswered counts as zero); best attempt applies with retakes; tab switches are recorded only.",
                    }
                  : {
                      zh: "成绩按每题第一次作答统计；练习重试不冲高正确率。",
                      en: "Stats use each item's first answer; practice retries don't inflate accuracy.",
                    },
              )}
            </p>
            <RoundSelector
              assignments={assignments}
              selectedAssignmentId={selectedAssignmentId}
              onSelect={onSelectAssignment}
              className="mt-2"
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void resultsQuery.refetch()}
            disabled={resultsQuery.isFetching}
          >
            <RefreshCw
              className={resultsQuery.isFetching ? "animate-spin" : ""}
            />
            {t({ zh: "刷新", en: "Refresh" })}
          </Button>
          <Button variant="outline" size="sm" onClick={() => void exportCsv()}>
            <Download />
            {t({ zh: "导出", en: "Export" })}
          </Button>
          {isQuiz && (
            <Button
              size="sm"
              variant={results?.grades_published ? "outline" : "default"}
              disabled={results?.grades_published === true}
              onClick={() => publishGrades.mutate(assignment.id)}
            >
              {t(
                results?.grades_published
                  ? { zh: "成绩已公布", en: "Grades published" }
                  : { zh: "公布成绩", en: "Publish grades" },
              )}
            </Button>
          )}
          {isQuiz && (
            <Button
              size="sm"
              variant={results?.answers_published ? "outline" : "default"}
              disabled={results?.answers_published === true}
              onClick={() => publishAnswers.mutate(assignment.id)}
            >
              {t(
                results?.answers_published
                  ? { zh: "答案已公布", en: "Answers published" }
                  : { zh: "公布答案", en: "Publish answers" },
              )}
            </Button>
          )}
          {assignment.status === "published" && (
            <Button
              variant="outline"
              size="sm"
              disabled={archive.isPending}
              onClick={() => archive.mutate(assignment.id)}
            >
              <Archive />
              {t({ zh: "结束任务", en: "End task" })}
            </Button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "逐词错误分布", en: "Per-word errors" })}
          </CardTitle>
          <CardDescription>
            {errorWords.length === 0
              ? t({
                  zh: "还没有错词——学生都还没开始，或首答全对。",
                  en: "No errors yet — either nobody started, or first tries are all correct.",
                })
              : t({
                  zh: "按首答统计；常见误拼取前 5，可据此安排课堂复习。",
                  en: "First answers only; top-5 misspellings shown to plan in-class review.",
                })}
            <span className="mt-1 block sm:hidden">
              {t({
                zh: "横向滑动表格，可以查看完整数据。",
                en: "Swipe the table sideways to see all data.",
              })}
            </span>
          </CardDescription>
        </CardHeader>
        <CardContent className="pb-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t({ zh: "单词", en: "Word" })}</TableHead>
                <TableHead>{t({ zh: "释义", en: "Meaning" })}</TableHead>
                <TableHead>
                  {t({ zh: "已答/名单", en: "Answered/Roster" })}
                </TableHead>
                <TableHead>
                  {t({ zh: "首答正确", en: "First-try correct" })}
                </TableHead>
                <TableHead>
                  {t({ zh: "常见误拼", en: "Common misspellings" })}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {words.map((word) => (
                <TableRow key={word.word_id}>
                  <TableCell className="font-semibold">
                    {word.headword}
                    <span className="ml-2 font-normal text-xs text-muted-foreground">
                      #{word.item_index + 1}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {word.meaning_zh}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {word.answered_count}/{target}
                  </TableCell>
                  <TableCell>
                    {word.error_count > 0 ? (
                      <span className="font-semibold tabular-nums">
                        {word.correct_first_count}
                        <span className="ml-1 text-xs font-normal text-muted-foreground">
                          ({t({ zh: "错", en: "miss" })} {word.error_count})
                        </span>
                      </span>
                    ) : (
                      <span className="tabular-nums">
                        {word.correct_first_count}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {(word.misspellings ?? []).length === 0
                      ? "–"
                      : (word.misspellings ?? []).map((miss) => (
                          <Badge
                            key={miss.answer}
                            variant="outline"
                            className="mr-1.5 font-mono"
                          >
                            {miss.answer}×{miss.count}
                          </Badge>
                        ))}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "学生完成情况", en: "Student completion" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "零作答显示「未开始」，不折算成 0% 正确率。",
              en: 'Zero answers show as "Not started", not 0% accuracy.',
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="pb-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t({ zh: "姓名", en: "Name" })}</TableHead>
                <TableHead>{t({ zh: "状态", en: "Status" })}</TableHead>
                {isQuiz ? (
                  <>
                    <TableHead>
                      {t({
                        zh: "答对/答错/未答",
                        en: "Right/Wrong/Unanswered",
                      })}
                    </TableHead>
                    <TableHead>
                      {t({ zh: "成绩（最好）", en: "Score (best)" })}
                    </TableHead>
                    <TableHead>
                      {t({ zh: "参与/切屏", en: "Attempts/Tab switches" })}
                    </TableHead>
                  </>
                ) : (
                  <>
                    <TableHead>{t({ zh: "已答", en: "Answered" })}</TableHead>
                    <TableHead>
                      {t({ zh: "首答正确", en: "First-try correct" })}
                    </TableHead>
                    <TableHead>
                      {t({ zh: "首答正确率", en: "First-try accuracy" })}
                    </TableHead>
                  </>
                )}
                <TableHead>
                  {t({ zh: "交卷时间", en: "Submitted at" })}
                </TableHead>
                {isQuiz && (
                  <TableHead>{t({ zh: "操作", en: "Actions" })}</TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {students.map((row) => {
                const name = row.suffix
                  ? `${row.display_name}·${row.suffix}`
                  : row.display_name
                if (isQuiz) {
                  const wrong = Math.max(
                    0,
                    row.answered_count - row.correct_first_count,
                  )
                  const unanswered = Math.max(
                    0,
                    row.total_count - row.answered_count,
                  )
                  return (
                    <TableRow key={row.student_id}>
                      <TableCell className="font-medium">
                        {name}
                        {row.retake_granted && (
                          <Badge
                            variant="outline"
                            className="ml-1.5 text-muted-foreground"
                          >
                            {t(TERMS.quizRetake)}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {row.status === "completed" ? (
                          row.quiz_end_reason === "timeout" ? (
                            <Badge
                              variant="outline"
                              className="text-amber-600"
                              title={t(EXPLAIN_QUIZ_TAB_SWITCH)}
                            >
                              <CircleDashed className="size-3" />
                              {t(TERMS.quizTimedOut)}
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="text-primary">
                              <CheckCircle2 className="size-3" />
                              {t(TERMS.quizSubmitted)}
                            </Badge>
                          )
                        ) : row.status === "in_progress" ? (
                          <Badge variant="secondary">
                            <CircleDashed className="size-3" />
                            {t(STUDENT_STATUS.in_progress)}
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">
                            {t(STUDENT_STATUS.not_started)}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {row.correct_first_count} / {wrong} /{" "}
                        <span className="text-muted-foreground">
                          {unanswered}
                        </span>
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {row.score !== null && row.score !== undefined ? (
                          <span>
                            <span
                              className={`font-semibold ${row.passed ? "text-primary" : "text-amber-600"}`}
                            >
                              {row.score}
                            </span>
                            <span className="ml-1 text-xs text-muted-foreground">
                              {row.passed
                                ? t({ zh: "及格", en: "pass" })
                                : t({ zh: "不及格", en: "below" })}
                            </span>
                            {/* 补考后多份答卷：标注有效成绩取自哪一轮 */}
                            {row.effective_round_no != null &&
                            (row.attempt_count ?? 0) > 1 ? (
                              <span
                                className="ml-1 text-xs text-muted-foreground"
                                title={t({
                                  zh: "有效成绩取自该轮答卷（答对/答错与成绩同源）",
                                  en: "Effective grade comes from this round (correct/wrong share the same paper)",
                                })}
                              >
                                {t({
                                  zh: `第${row.effective_round_no}轮`,
                                  en: `R${row.effective_round_no}`,
                                })}
                              </span>
                            ) : null}
                          </span>
                        ) : (
                          "–"
                        )}
                      </TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">
                        {row.attempt_count ?? 0} / {row.tab_switch_count ?? 0}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {row.submitted_at
                          ? formatTime(row.submitted_at, lang)
                          : "–"}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1.5">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={
                              (row.attempt_count ?? 0) === 0 &&
                              row.status === "not_started"
                            }
                            onClick={() => {
                              setSheetRoundNo(null)
                              setSheetStudent(row)
                            }}
                          >
                            {t({ zh: "答卷", en: "Answers" })}
                          </Button>
                          {!row.retake_granted && (
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={grantRetake.isPending}
                              onClick={() =>
                                grantRetake.mutate({
                                  assignmentId: assignment.id,
                                  studentId: row.student_id,
                                })
                              }
                            >
                              {t({ zh: "授权补考", en: "Grant retake" })}
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                }
                return (
                  <TableRow key={row.student_id}>
                    <TableCell className="font-medium">{name}</TableCell>
                    <TableCell>
                      {row.status === "completed" ? (
                        <Badge variant="outline" className="text-primary">
                          <CheckCircle2 className="size-3" />
                          {t(STUDENT_STATUS.completed)}
                        </Badge>
                      ) : row.status === "in_progress" ? (
                        <Badge variant="secondary">
                          <CircleDashed className="size-3" />
                          {t(STUDENT_STATUS.in_progress)}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">
                          {t(STUDENT_STATUS.not_started)}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {row.answered_count}/{row.total_count}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {row.correct_first_count}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {row.answered_count > 0
                        ? `${Math.round((row.correct_first_count / row.answered_count) * 100)}%`
                        : "–"}
                    </TableCell>
                    <TableCell>
                      {(row.rounds ?? []).length > 1 ? (
                        <span className="flex flex-wrap gap-1">
                          {(row.rounds ?? []).map((round) => (
                            <Badge
                              key={round.round_no}
                              variant={
                                round.round_no === 1 ? "secondary" : "outline"
                              }
                              className="tabular-nums"
                              title={t({
                                zh: `第 ${round.round_no} 轮：首答 ${round.correct_first_count}/${round.answered_count}${round.status === "submitted" ? "（已完成）" : "（未完成）"}`,
                                en: `Round ${round.round_no}: ${round.correct_first_count}/${round.answered_count} first-try${round.status === "submitted" ? " (finished)" : " (unfinished)"}`,
                              })}
                            >
                              R{round.round_no} {round.correct_first_count}/
                              {round.answered_count}
                            </Badge>
                          ))}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">–</span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {row.submitted_at
                        ? formatTime(row.submitted_at, lang)
                        : "–"}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <p className="pb-6 text-center text-xs text-muted-foreground">
        {t({
          zh: "统计只看每题第一次作答，帮助学生看见真实起点；练习数据辅助教学，不定义学生。",
          en: "Stats reflect each item's first answer, showing students' real starting points. Practice data supports teaching — it doesn't define students.",
        })}
      </p>

      {isQuiz && (
        <QuizAnswerSheetDialog
          code={code}
          assignmentId={assignment.id}
          student={sheetStudent}
          roundNo={sheetRoundNo}
          onClose={() => setSheetStudent(null)}
        />
      )}
    </div>
  )
}
