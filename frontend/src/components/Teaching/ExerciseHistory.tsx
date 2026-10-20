import { useQuery } from "@tanstack/react-query"
import { ArrowUpRight, Download, FileText, History } from "lucide-react"
import { useCallback, useState } from "react"
import type { ClassroomExercisePublic, ExerciseStudentResult } from "@/client"
import { ClassesService } from "@/client"
import { AttemptFeedbackDialog } from "@/components/Teaching/AttemptFeedbackDialog"
import { CopyExerciseDialog } from "@/components/Teaching/CopyExerciseDialog"
import { LessonReview } from "@/components/Teaching/LessonReview"
import { RecordingButton } from "@/components/Teaching/RecordingButton"
import { StudentFeedbackDialog } from "@/components/Teaching/StudentFeedbackDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { downloadCsv } from "@/lib/csv"
import { useI18n } from "@/lib/i18n"
import { pollWhileVisible } from "@/lib/poll"
import { ITEM_TYPE_LABELS } from "@/lib/terms"
import { formatDateTime } from "@/lib/time"

/** 时长标签：60 秒内显示秒，超过显示「分 秒」（中英文各自习惯格式）。 */
function formatDurationLabel(
  t: (bi: { zh: string; en: string }) => string,
  seconds: number,
): string {
  if (seconds < 60) return t({ zh: `${seconds} 秒`, en: `${seconds}s` })
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  if (s === 0) return t({ zh: `${m} 分钟`, en: `${m}m` })
  return t({ zh: `${m} 分 ${s} 秒`, en: `${m}m${s}s` })
}

/** 发布历史：每次发布的练习（快照）列表 + 按次结果回看与导出。 */
export function ExerciseHistory({
  code,
  initialExerciseId,
  onCopied,
  onReviewDirtyChange,
}: {
  code: string
  initialExerciseId?: string | null
  onReviewDirtyChange?: (dirty: boolean) => void
  onCopied?: () => void
}) {
  const { t } = useI18n()
  const [copying, setCopying] = useState<ClassroomExercisePublic | null>(null)
  const exercisesQuery = useQuery({
    queryKey: ["teacher", "exercises", code],
    queryFn: () =>
      ClassesService.listClassroomExercises({ code: code.toUpperCase() }),
  })
  const [selectedId, setSelectedId] = useState<string | null>(
    initialExerciseId ?? null,
  )

  if (exercisesQuery.isPending)
    return (
      <p className="rounded-xl border p-6 text-muted-foreground">
        {t({
          zh: "正在加载发布历史…",
          en: "Loading publish history…",
        })}
      </p>
    )
  if (exercisesQuery.isError)
    return (
      <div className="rounded-xl border p-6 text-muted-foreground">
        {t({ zh: "发布历史加载失败。", en: "Failed to load publish history." })}
        <Button
          variant="outline"
          size="sm"
          className="ml-3"
          onClick={() => void exercisesQuery.refetch()}
        >
          {t({ zh: "重试", en: "Retry" })}
        </Button>
      </div>
    )

  const exercises = exercisesQuery.data
  const selected = exercises.find((exercise) => exercise.id === selectedId)
  if (exercises.length === 0)
    return (
      <p className="rounded-xl border bg-card p-6 text-center text-muted-foreground">
        {t({
          zh: "还没有发布过练习。第一次发布后会在这里留档，可随时回看每次练习的结果。",
          en: "Nothing published yet. Each publish is archived here so you can review its results anytime.",
        })}
      </p>
    )

  if (selected)
    return (
      <ExerciseResults
        code={code}
        exercise={selected}
        onBack={() => setSelectedId(null)}
        onReviewDirtyChange={onReviewDirtyChange}
      />
    )

  return (
    <div className="space-y-4">
      {copying && (
        <CopyExerciseDialog
          code={code}
          exercise={copying}
          onClose={() => setCopying(null)}
          onCopied={onCopied}
        />
      )}
      <div className="flex items-center gap-3 rounded-xl border border-primary/10 bg-primary/5 p-4">
        <History className="size-5 shrink-0 text-primary" />
        <div>
          <h2 className="font-semibold">
            {t({ zh: "发布记录", en: "Published activities" })}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t({
              zh: `共 ${exercises.length} 次发布 · 按发布时的题单查看反馈`,
              en: `${exercises.length} activities · Review feedback against the published items`,
            })}
          </p>
        </div>
      </div>
      {exercises.map((exercise) => (
        <Card
          key={exercise.id}
          className="gap-0 border-primary/10 shadow-none transition-shadow hover:shadow-sm"
        >
          <CardContent className="flex flex-wrap items-center justify-between gap-4 py-5">
            <div>
              <p className="break-words font-semibold">
                v{exercise.version_no} · {exercise.title}
              </p>
              <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge
                  variant={
                    exercise.status === "published" ? "outline" : "secondary"
                  }
                >
                  {exercise.status === "published"
                    ? t({ zh: "当前发布", en: "Current publish" })
                    : t({ zh: "已归档", en: "Archived" })}
                </Badge>
                <span>
                  {t({
                    zh: `${exercise.item_count} 道题`,
                    en: `${exercise.item_count} items`,
                  })}
                </span>
                {exercise.published_at && (
                  <span>
                    {t({
                      zh: `发布于 ${formatDateTime(exercise.published_at, "zh")}`,
                      en: `Published ${formatDateTime(exercise.published_at, "en")}`,
                    })}
                  </span>
                )}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                className="min-h-11"
                onClick={() => setCopying(exercise)}
              >
                {t({ zh: "复制练习", en: "Copy practice" })}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="min-h-11"
                onClick={() => setSelectedId(exercise.id)}
              >
                {t({ zh: "查看结果", en: "View Results" })}
                <ArrowUpRight className="size-4" />
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function ExerciseResults({
  code,
  exercise,
  onBack,
  onReviewDirtyChange,
}: {
  code: string
  exercise: ClassroomExercisePublic
  onBack: () => void
  onReviewDirtyChange?: (dirty: boolean) => void
}) {
  const { t } = useI18n()
  const [reviewDirty, setReviewDirty] = useState(false)
  const reviewChanged = useCallback(
    (dirty: boolean) => {
      setReviewDirty(dirty)
      onReviewDirtyChange?.(dirty)
    },
    [onReviewDirtyChange],
  )
  const [feedbackStudent, setFeedbackStudent] =
    useState<ExerciseStudentResult | null>(null)
  const [feedbackAttemptId, setFeedbackAttemptId] = useState<string | null>(
    null,
  )
  const resultsQuery = useQuery({
    queryKey: ["teacher", "exercise-results", code, exercise.id],
    queryFn: () =>
      ClassesService.readExerciseResults({
        code: code.toUpperCase(),
        exerciseId: exercise.id,
      }),
    // 有学生在评分中时 5 秒刷新（与学生结果面板口径一致），否则不轮询
    refetchInterval: pollWhileVisible((query) =>
      (query.state.data ?? []).some((row) => row.has_pending) ? 5000 : false,
    ),
  })

  const exportCsv = (rows: ExerciseStudentResult[]) => {
    // 每题一列：分数或未做；模考发布附监考列（紧跟姓名，方便老师先看异常）
    const itemColumns =
      rows[0]?.items.map((_, idx) =>
        t({ zh: `第${idx + 1}题`, en: `Item ${idx + 1}` }),
      ) ?? []
    const isExam = exercise.is_exam
    const examHeaders = isExam
      ? [
          t({ zh: "切屏次数", en: "Switches" }),
          t({ zh: "离屏秒数", en: "Away seconds" }),
          t({ zh: "用时秒数", en: "Time used (s)" }),
          t({ zh: "交卷状态", en: "Submission" }),
        ]
      : []
    downloadCsv(
      [
        [
          t({ zh: "姓名", en: "Name" }),
          ...examHeaders,
          t({ zh: "完成", en: "Done" }),
          t({ zh: "总题数", en: "Total Items" }),
          ...itemColumns,
        ],
        ...rows.map((row) => [
          row.suffix ? `${row.display_name}·${row.suffix}` : row.display_name,
          ...(isExam
            ? [
                row.exam_tab_switches ?? "",
                row.exam_tab_switch_seconds ?? "",
                row.exam_time_used_seconds ?? "",
                row.exam_ended == null
                  ? ""
                  : row.exam_ended
                    ? t({ zh: "已交卷", en: "Submitted" })
                    : t({ zh: "进行中", en: "In progress" }),
              ]
            : []),
          row.done_count,
          row.total_count,
          ...row.items.map((item) =>
            item.status === "done"
              ? (item.overall ?? "-")
              : item.status === "missing"
                ? t({ zh: "未做", en: "Missing" })
                : item.status === "failed"
                  ? t({ zh: "未评出", en: "No Score" })
                  : t({ zh: "评分中", en: "Scoring" }),
          ),
        ]),
      ],
      t({
        zh: `练习v${exercise.version_no}-${exercise.title}.csv`,
        en: `practice-v${exercise.version_no}-${exercise.title}.csv`,
      }),
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/10 bg-primary/5 p-4">
        <div>
          <Button
            variant="ghost"
            size="sm"
            className="mb-1 min-h-11 px-0"
            onClick={() => {
              if (
                !reviewDirty ||
                window.confirm(
                  t({
                    zh: "放弃未保存的讲评修改？",
                    en: "Discard unsaved discussion edits?",
                  }),
                )
              )
                onBack()
            }}
          >
            ← {t({ zh: "发布历史", en: "Publish History" })}
          </Button>
          <p className="break-words font-semibold">
            v{exercise.version_no} · {exercise.title}
          </p>
        </div>
        {!resultsQuery.isPending && (resultsQuery.data?.length ?? 0) > 0 && (
          <Button
            variant="outline"
            size="sm"
            className="min-h-11"
            onClick={() => exportCsv(resultsQuery.data!)}
          >
            <Download />
            {t({ zh: "导出成绩 CSV", en: "Export Grades CSV" })}
          </Button>
        )}
      </div>
      {resultsQuery.isSuccess && (
        <LessonReview
          code={code}
          exerciseId={exercise.id}
          students={resultsQuery.data}
          isExam={exercise.is_exam === true}
          onDirtyChange={reviewChanged}
        />
      )}
      {resultsQuery.isPending ? (
        <p className="rounded-xl border p-6 text-muted-foreground">
          {t({ zh: "正在加载结果…", en: "Loading results…" })}
        </p>
      ) : resultsQuery.isError ? (
        <p className="rounded-xl border p-6 text-muted-foreground">
          {t({
            zh: "结果加载失败，请重试。",
            en: "Failed to load results, please retry.",
          })}
        </p>
      ) : (
        <Card className="gap-0 overflow-hidden border-primary/10 shadow-sm">
          <CardHeader className="border-b bg-muted/30 pb-5">
            <CardTitle className="text-base">
              {t({
                zh: `按「${exercise.title}」发布的题单解释（${exercise.item_count} 道题）`,
                en: `Items published for "${exercise.title}" (${exercise.item_count} items)`,
              })}
              {exercise.is_exam && (
                <Badge variant="destructive" className="ml-2 align-middle">
                  {t({ zh: "模考", en: "Exam" })} ·{" "}
                  {exercise.time_limit_minutes}
                  {t({ zh: " 分钟", en: " min" })}
                </Badge>
              )}
            </CardTitle>
            <p className="mt-1 block text-xs text-muted-foreground hidden lg:block">
              {t({
                zh: "横向滑动表格，可以查看完整内容。",
                en: "Swipe the table sideways to see everything.",
              })}
            </p>
          </CardHeader>
          <CardContent className="pt-5">
            <Table className="block lg:table">
              <TableHeader className="hidden lg:table-header-group">
                <TableRow>
                  <TableHead>{t({ zh: "姓名", en: "Name" })}</TableHead>
                  <TableHead>{t({ zh: "完成", en: "Done" })}</TableHead>
                  {(resultsQuery.data?.[0]?.items ?? []).map((item, idx) => (
                    <TableHead key={item.item_id} className="whitespace-nowrap">
                      {idx + 1}.{" "}
                      {t(
                        ITEM_TYPE_LABELS[item.type] ?? {
                          zh: item.type,
                          en: item.type,
                        },
                      )}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody className="block space-y-4 lg:table-row-group lg:space-y-0">
                {(resultsQuery.data ?? []).map((row) => (
                  <TableRow
                    key={row.student_id}
                    className="grid grid-cols-1 gap-3 rounded-xl border bg-card p-4 sm:grid-cols-2 lg:table-row lg:rounded-none lg:border-x-0 lg:border-t-0 lg:p-0"
                  >
                    <TableCell className="block whitespace-normal font-medium sm:col-span-2 lg:table-cell">
                      {row.suffix
                        ? `${row.display_name}·${row.suffix}`
                        : row.display_name}
                      {row.has_pending && (
                        <Badge variant="secondary" className="ml-2">
                          {t({ zh: "评分中", en: "Scoring" })}
                        </Badge>
                      )}
                      {exercise.is_exam && row.exam_tab_switches != null && (
                        <Badge
                          variant={
                            row.exam_tab_switches ? "destructive" : "outline"
                          }
                          className="ml-2"
                        >
                          {t({ zh: "切屏", en: "Switches" })}{" "}
                          {row.exam_tab_switches}
                          {row.exam_tab_switch_seconds
                            ? ` · ${formatDurationLabel(t, row.exam_tab_switch_seconds)}`
                            : ""}
                        </Badge>
                      )}
                      {exercise.is_exam &&
                        row.exam_time_used_seconds != null && (
                          <Badge variant="secondary" className="ml-2">
                            {row.exam_ended
                              ? t({ zh: "已交卷", en: "Submitted" })
                              : t({ zh: "进行中", en: "In progress" })}
                            {` · ${formatDurationLabel(t, row.exam_time_used_seconds)}`}
                          </Badge>
                        )}
                      <Button
                        variant="ghost"
                        size="sm"
                        className="mt-1 flex min-h-11"
                        onClick={() => setFeedbackStudent(row)}
                      >
                        {t({ zh: "汇总反馈", en: "Overall feedback" })}
                      </Button>
                    </TableCell>
                    <TableCell className="block whitespace-nowrap text-sm tabular-nums sm:col-span-2 lg:table-cell">
                      <span className="mr-2 text-muted-foreground lg:hidden">
                        {t({ zh: "完成", en: "Done" })}
                      </span>
                      {row.done_count}/{row.total_count}
                    </TableCell>
                    {row.items.map((item, index) => (
                      <TableCell
                        key={item.item_id}
                        className="block min-w-0 rounded-lg bg-muted/40 p-3 whitespace-normal lg:table-cell lg:rounded-none lg:bg-transparent"
                      >
                        <p className="mb-2 text-xs font-medium text-muted-foreground lg:hidden">
                          {index + 1}.{" "}
                          {t(
                            ITEM_TYPE_LABELS[item.type] ?? {
                              zh: item.type,
                              en: item.type,
                            },
                          )}
                        </p>
                        {item.status === "done" ? (
                          <span className="font-semibold tabular-nums">
                            {item.overall ?? "-"}
                          </span>
                        ) : item.status === "missing" ? (
                          <span className="text-muted-foreground">
                            {t({ zh: "未做", en: "Missing" })}
                          </span>
                        ) : item.status === "failed" ? (
                          <span className="text-destructive">
                            {t({ zh: "未评出", en: "No Score" })}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">
                            {t({ zh: "评分中", en: "Scoring" })}
                          </span>
                        )}
                        {item.attempt_id && (
                          <div className="mt-1 flex flex-col items-start gap-1">
                            <RecordingButton
                              key={item.attempt_id}
                              attemptId={item.attempt_id}
                              label={t({
                                zh: `回听 ${row.display_name} 第${index + 1}题录音`,
                                en: `Listen to ${row.display_name}'s recording for item ${index + 1}`,
                              })}
                            />
                            {item.status === "done" && (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="min-h-11"
                                aria-label={t({
                                  zh: `查看 ${row.display_name} 第${index + 1}题详细反馈`,
                                  en: `View detailed feedback for ${row.display_name}'s item ${index + 1}`,
                                })}
                                onClick={() =>
                                  setFeedbackAttemptId(item.attempt_id!)
                                }
                              >
                                <FileText className="size-4" />
                                {t({ zh: "详细反馈", en: "Feedback" })}
                              </Button>
                            )}
                          </div>
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {(resultsQuery.data ?? []).some((row) =>
              row.items.some((item) => item.attempt_id),
            ) && (
              <p className="mt-3 text-xs text-muted-foreground">
                {t({
                  zh: "分数为教学参考；点击「听录音」回听该发布版本的作答，「详细反馈」可看转写与逐题建议。",
                  en: "Scores are teaching references. Recording plays the answer from this published version; Feedback shows the transcript and per-item tips.",
                })}
              </p>
            )}
          </CardContent>
        </Card>
      )}
      <StudentFeedbackDialog
        name={feedbackStudent?.display_name ?? ""}
        items={
          (
            resultsQuery.data?.find(
              (row) => row.student_id === feedbackStudent?.student_id,
            ) ?? feedbackStudent
          )?.items ?? []
        }
        open={feedbackStudent !== null}
        onClose={() => setFeedbackStudent(null)}
      />
      <AttemptFeedbackDialog
        attemptId={feedbackAttemptId}
        open={feedbackAttemptId !== null}
        onClose={() => setFeedbackAttemptId(null)}
      />
    </div>
  )
}
