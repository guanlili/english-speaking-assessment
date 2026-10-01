import { useQuery } from "@tanstack/react-query"
import { Download } from "lucide-react"
import { useState } from "react"
import type { ClassroomExercisePublic, ExerciseStudentResult } from "@/client"
import { ClassesService } from "@/client"
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

/** 发布历史：每次发布的练习（快照）列表 + 按次结果回看与导出。 */
export function ExerciseHistory({ code }: { code: string }) {
  const { t } = useI18n()
  const exercisesQuery = useQuery({
    queryKey: ["teacher", "exercises", code],
    queryFn: () =>
      ClassesService.listClassroomExercises({ code: code.toUpperCase() }),
  })
  const [selected, setSelected] = useState<ClassroomExercisePublic | null>(null)

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
        onBack={() => setSelected(null)}
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
                      zh: `发布于 ${new Date(exercise.published_at).toLocaleString("zh-CN")}`,
                      en: `Published ${new Date(exercise.published_at).toLocaleString("zh-CN")}`,
                    })}
                  </span>
                )}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSelected(exercise)}
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
    // 每题一列：分数或未做
    const itemColumns =
      rows[0]?.items.map((_, idx) =>
        t({ zh: `第${idx + 1}题`, en: `Item ${idx + 1}` }),
      ) ?? []
    downloadCsv(
      [
        [
          t({ zh: "姓名", en: "Name" }),
          t({ zh: "完成", en: "Done" }),
          t({ zh: "总题数", en: "Total Items" }),
          ...itemColumns,
        ],
        ...rows.map((row) => [
          row.suffix ? `${row.display_name}·${row.suffix}` : row.display_name,
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
                        </Badge>
                      )}
                      {exercise.is_exam &&
                        row.exam_time_used_seconds != null && (
                          <Badge variant="secondary" className="ml-2">
                            {row.exam_ended
                              ? t({ zh: "已交卷", en: "Submitted" })
                              : t({ zh: "进行中", en: "In progress" })}
                          </Badge>
                        )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {row.done_count}/{row.total_count}
                    </TableCell>
                    {row.items.map((item) => (
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
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {(resultsQuery.data ?? []).some((row) =>
              row.items.some(
                (item) => item.attempt_id && item.status === "done",
              ),
            ) && (
              <p className="mt-3 text-xs text-muted-foreground">
                {t({
                  zh: "分数为参考反馈；录音请在「学生结果」面板按学生展开回听。",
                  en: "Scores are reference feedback; listen to recordings by expanding students in the Student Results panel.",
                })}
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
