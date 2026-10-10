import { useQuery } from "@tanstack/react-query"
import { Download, Volume2 } from "lucide-react"
import { useState } from "react"
import type { ClassroomExercisePublic, ExerciseStudentResult } from "@/client"
import { ClassesService } from "@/client"
import AttemptAudio from "@/components/Practice/AttemptAudio"
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
}: {
  code: string
  initialExerciseId?: string | null
}) {
  const { t } = useI18n()
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
      />
    )

  return (
    <div className="space-y-3">
      {exercises.map((exercise) => (
        <Card key={exercise.id}>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
            <div>
              <p className="font-semibold">
                v{exercise.version_no} · {exercise.title}
              </p>
              <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
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
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSelectedId(exercise.id)}
            >
              {t({ zh: "查看结果", en: "View Results" })}
            </Button>
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
}: {
  code: string
  exercise: ClassroomExercisePublic
  onBack: () => void
}) {
  const { t } = useI18n()
  const [recording, setRecording] = useState<{
    id: string
    label: string
  } | null>(null)
  const resultsQuery = useQuery({
    queryKey: ["teacher", "exercise-results", code, exercise.id],
    queryFn: () =>
      ClassesService.readExerciseResults({
        code: code.toUpperCase(),
        exerciseId: exercise.id,
      }),
    // 有学生在评分中时 5 秒刷新（与学生结果面板口径一致），否则不轮询
    refetchInterval: (query) =>
      (query.state.data ?? []).some((row) => row.has_pending) ? 5000 : false,
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Button
            variant="ghost"
            size="sm"
            className="mb-1 px-0"
            onClick={onBack}
          >
            ← {t({ zh: "发布历史", en: "Publish History" })}
          </Button>
          <p className="font-semibold">
            v{exercise.version_no} · {exercise.title}
          </p>
        </div>
        {!resultsQuery.isPending && (resultsQuery.data?.length ?? 0) > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => exportCsv(resultsQuery.data!)}
          >
            <Download />
            {t({ zh: "导出成绩 CSV", en: "Export Grades CSV" })}
          </Button>
        )}
      </div>
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
        <Card>
          <CardHeader>
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
            <p className="mt-1 block text-xs text-muted-foreground sm:hidden">
              {t({
                zh: "横向滑动表格，可以查看完整内容。",
                en: "Swipe the table sideways to see everything.",
              })}
            </p>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
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
              <TableBody>
                {(resultsQuery.data ?? []).map((row) => (
                  <TableRow key={row.student_id}>
                    <TableCell className="font-medium">
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
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {row.done_count}/{row.total_count}
                    </TableCell>
                    {row.items.map((item, index) => (
                      <TableCell key={item.item_id}>
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
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="mt-1 min-h-11"
                            aria-label={t({
                              zh: `回听 ${row.display_name} 第${index + 1}题录音`,
                              en: `Listen to ${row.display_name}'s recording for item ${index + 1}`,
                            })}
                            onClick={() => {
                              if (item.attempt_id)
                                setRecording({
                                  id: item.attempt_id,
                                  label: t({
                                    zh: `${row.display_name} · 第${index + 1}题`,
                                    en: `${row.display_name} · Item ${index + 1}`,
                                  }),
                                })
                            }}
                          >
                            <Volume2 className="size-4" />
                            {t({ zh: "听录音", en: "Recording" })}
                          </Button>
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {recording && (
              <div className="mt-4 space-y-2 rounded-xl border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium">
                    v{exercise.version_no} · {recording.label}
                  </p>
                  <Button
                    type="button"
                    variant="ghost"
                    className="min-h-11"
                    onClick={() => setRecording(null)}
                  >
                    {t({ zh: "收起录音", en: "Close recording" })}
                  </Button>
                </div>
                <AttemptAudio
                  key={recording.id}
                  attemptId={recording.id}
                  className="w-full"
                />
              </div>
            )}
            {(resultsQuery.data ?? []).some((row) =>
              row.items.some((item) => item.attempt_id),
            ) && (
              <p className="mt-3 text-xs text-muted-foreground">
                {t({
                  zh: "分数为教学参考；点击「听录音」回听该发布版本的作答。",
                  en: "Scores are teaching references. Select Recording to listen to answers from this published version.",
                })}
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
