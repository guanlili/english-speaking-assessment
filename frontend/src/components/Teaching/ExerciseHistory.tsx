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
import { ITEM_TYPE_LABELS } from "@/lib/terms"

/** 发布历史：每次发布的练习（快照）列表 + 按次结果回看与导出。 */
export function ExerciseHistory({ code }: { code: string }) {
  const exercisesQuery = useQuery({
    queryKey: ["teacher", "exercises", code],
    queryFn: () =>
      ClassesService.listClassroomExercises({ code: code.toUpperCase() }),
  })
  const [selected, setSelected] = useState<ClassroomExercisePublic | null>(null)

  if (exercisesQuery.isPending)
    return (
      <p className="rounded-xl border p-6 text-muted-foreground">
        正在加载发布历史…
      </p>
    )
  if (exercisesQuery.isError)
    return (
      <div className="rounded-xl border p-6 text-muted-foreground">
        发布历史加载失败。
        <Button
          variant="outline"
          size="sm"
          className="ml-3"
          onClick={() => void exercisesQuery.refetch()}
        >
          重试
        </Button>
      </div>
    )

  const exercises = exercisesQuery.data
  if (exercises.length === 0)
    return (
      <p className="rounded-xl border bg-card p-6 text-center text-muted-foreground">
        还没有发布过练习。第一次发布后会在这里留档，可随时回看每次练习的结果。
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
                  {exercise.status === "published" ? "当前发布" : "已归档"}
                </Badge>
                <span>{exercise.item_count} 道题</span>
                {exercise.published_at && (
                  <span>
                    发布于{" "}
                    {new Date(exercise.published_at).toLocaleString("zh-CN")}
                  </span>
                )}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSelected(exercise)}
            >
              查看结果
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
    const itemColumns = rows[0]?.items.map((_, idx) => `第${idx + 1}题`) ?? []
    downloadCsv(
      [
        ["姓名", "完成", "总题数", ...itemColumns],
        ...rows.map((row) => [
          row.suffix ? `${row.display_name}·${row.suffix}` : row.display_name,
          row.done_count,
          row.total_count,
          ...row.items.map((item) =>
            item.status === "done"
              ? (item.overall ?? "-")
              : item.status === "missing"
                ? "未做"
                : item.status === "failed"
                  ? "未评出"
                  : "评分中",
          ),
        ]),
      ],
      `练习v${exercise.version_no}-${exercise.title}.csv`,
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
            ← 发布历史
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
            导出成绩 CSV
          </Button>
        )}
      </div>
      {resultsQuery.isPending ? (
        <p className="rounded-xl border p-6 text-muted-foreground">
          正在加载结果…
        </p>
      ) : resultsQuery.isError ? (
        <p className="rounded-xl border p-6 text-muted-foreground">
          结果加载失败，请重试。
        </p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              按「{exercise.title}」发布的题单解释（{exercise.item_count} 道题）
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>姓名</TableHead>
                  <TableHead>完成</TableHead>
                  {(resultsQuery.data?.[0]?.items ?? []).map((item, idx) => (
                    <TableHead key={item.item_id} className="whitespace-nowrap">
                      {idx + 1}. {ITEM_TYPE_LABELS[item.type] ?? item.type}
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
                          评分中
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
                          <span className="text-muted-foreground">未做</span>
                        ) : item.status === "failed" ? (
                          <span className="text-destructive">未评出</span>
                        ) : (
                          <span className="text-muted-foreground">评分中</span>
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
                分数为参考反馈；录音请在「学生结果」面板按学生展开回听。
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
