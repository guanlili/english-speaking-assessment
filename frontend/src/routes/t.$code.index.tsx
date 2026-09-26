import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
  Target,
} from "lucide-react"
import { useState } from "react"
import type { BoardStudent } from "@/client"
import { ClassesService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { APP_NAME } from "@/config"

export const Route = createFileRoute("/t/$code/")({
  component: TeacherBoardPage,
  head: () => ({
    meta: [{ title: `课堂面板 - ${APP_NAME}` }],
  }),
})

const API_BASE = import.meta.env.VITE_API_URL ?? ""

const TYPE_LABELS: Record<string, string> = {
  repeat: "复述",
  question: "问答",
}

// 有学生在评分中时的轮询间隔（PRD US-10：最后一人提交后 2 分钟内一致）
const PENDING_REFRESH_MS = 5000

function audioUrl(attemptId: string): string {
  return `${API_BASE}/api/v1/attempts/${attemptId}/audio`
}

function TeacherBoardPage() {
  const { code } = useParams({ from: "/t/$code/" })
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const boardQuery = useQuery({
    queryKey: ["teacher", "board", code],
    queryFn: () => ClassesService.readClassBoard({ code: code.toUpperCase() }),
    refetchInterval: (query) =>
      (query.state.data?.pending_count ?? 0) > 0 ? PENDING_REFRESH_MS : false,
  })

  const queryClient = useQueryClient()
  const unitsQuery = useQuery({
    queryKey: ["teacher", "units", code],
    queryFn: () =>
      ClassesService.listUnitsForClass({ code: code.toUpperCase() }),
  })

  const assignMutation = useMutation({
    mutationFn: (unitId: string | null) =>
      ClassesService.setAssignment({
        code: code.toUpperCase(),
        requestBody: { unit_id: unitId },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teacher", "board", code] })
    },
  })

  if (boardQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        正在加载课堂面板…
      </div>
    )
  }
  if (boardQuery.isError || !boardQuery.data) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-muted-foreground">
        课堂不存在或已关闭，请核对链接里的课堂码。
        <Button variant="outline" onClick={() => boardQuery.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  const board = boardQuery.data
  const hasStudents = board.students.length > 0

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 p-6">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">课堂面板</h1>
            <p className="text-sm text-muted-foreground">
              课堂 {board.classroom_code} · 已交 {board.submitted_count}/
              {board.class_size}
              {board.pending_count > 0 && (
                <span className="ml-2 inline-flex items-center gap-1">
                  <Loader2 className="size-3 animate-spin" />
                  {board.pending_count} 人评分中
                </span>
              )}
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              <Badge variant="secondary">
                评分引擎：{board.engine === "ark" ? "方舟（AI）" : "演示模式"}
              </Badge>
            </div>
            {/* 三档分布（PRD US-10） */}
            <div className="mt-1 flex flex-wrap gap-1">
              {Object.entries(board.band_distribution).map(([band, count]) => (
                <Badge key={band} variant="outline">
                  {band} × {count}
                </Badge>
              ))}
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => boardQuery.refetch()}
            disabled={boardQuery.isFetching}
          >
            <RefreshCw
              className={boardQuery.isFetching ? "animate-spin" : ""}
            />
            刷新
          </Button>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Target className="size-4 text-primary" />
              今日课堂指派
            </CardTitle>
            <CardDescription>
              指派后全班学生打开练习页就是该单元（课堂教学同步）；清除则回到学生个人进度
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2">
            {(unitsQuery.data ?? []).map((u) => (
              <Button
                key={u.unit_id}
                size="sm"
                variant={
                  board.assignment?.unit_id === u.unit_id
                    ? "default"
                    : "outline"
                }
                onClick={() => assignMutation.mutate(u.unit_id)}
                disabled={assignMutation.isPending}
              >
                {u.title}
              </Button>
            ))}
            {board.assignment && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => assignMutation.mutate(null)}
                disabled={assignMutation.isPending}
              >
                清除指派
              </Button>
            )}
            {!board.assignment && (
              <span className="text-sm text-muted-foreground">
                未指派（学生按个人关卡进度练习）
              </span>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">今日名单</CardTitle>
            <CardDescription>
              点击一行展开每题分数和音频。分数是参考反馈，不是考试成绩。
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!hasStudents ? (
              <p className="py-8 text-center text-muted-foreground">
                还没有学生进入这个课堂。
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8" />
                    <TableHead>姓名</TableHead>
                    <TableHead>完成</TableHead>
                    <TableHead>跟读均分</TableHead>
                    <TableHead>问答均分</TableHead>
                    <TableHead>状态</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {board.students.map((student) => (
                    <StudentRow
                      key={student.student_id}
                      student={student}
                      code={code}
                      expanded={expandedId === student.student_id}
                      onToggle={() =>
                        setExpandedId(
                          expandedId === student.student_id
                            ? null
                            : student.student_id,
                        )
                      }
                    />
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <p className="pb-6 text-center text-xs text-muted-foreground">
          数据在评分完成后出现；有「评分中」时页面每几秒自动刷新。
        </p>
      </div>
    </div>
  )
}

function StudentRow({
  student,
  code,
  expanded,
  onToggle,
}: {
  student: BoardStudent
  code: string
  expanded: boolean
  onToggle: () => void
}) {
  const name = student.suffix
    ? `${student.display_name}·${student.suffix}`
    : student.display_name

  return (
    <>
      <TableRow onClick={onToggle} className="cursor-pointer">
        <TableCell>
          {expanded ? (
            <ChevronDown className="size-4" />
          ) : (
            <ChevronRight className="size-4" />
          )}
        </TableCell>
        <TableCell className="font-medium">{name}</TableCell>
        <TableCell>
          {student.done_count}/{student.total_count}
        </TableCell>
        <TableCell>{student.repeat_avg ?? "–"}</TableCell>
        <TableCell>{student.question_avg ?? "–"}</TableCell>
        <TableCell className="space-x-1 whitespace-nowrap">
          {student.inactive_days7 && (
            <Badge variant="destructive">7 日未练</Badge>
          )}
          {student.has_pending ? (
            <Badge variant="secondary">评分中</Badge>
          ) : student.done_count === 0 ? (
            <span className="text-muted-foreground">未提交</span>
          ) : (
            <Badge variant="outline">已交</Badge>
          )}
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow>
          <TableCell colSpan={6}>
            <div className="space-y-2 py-1">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">
                  当前练习档：{student.current_band}
                </span>
                <Button variant="link" size="sm" asChild>
                  <Link
                    to="/t/$code/s/$studentId"
                    params={{ code, studentId: student.student_id }}
                  >
                    查看进步轨迹 →
                  </Link>
                </Button>
              </div>
              {student.items.every((i) => i.status === "missing") && (
                <p className="text-sm text-muted-foreground">还没有作答。</p>
              )}
              {student.items.map((item, index) => (
                <div
                  key={item.item_id}
                  className="flex flex-wrap items-center gap-3 rounded-md border px-3 py-2"
                >
                  <span className="w-20 text-sm text-muted-foreground">
                    {index + 1}. {TYPE_LABELS[item.type] ?? item.type}
                  </span>
                  {item.status === "missing" ? (
                    <span className="text-sm text-muted-foreground">未做</span>
                  ) : item.status === "done" ? (
                    <span className="text-sm font-semibold tabular-nums">
                      总评 {item.overall ?? "–"}
                    </span>
                  ) : item.status === "failed" ? (
                    <span className="text-sm text-destructive">未评出</span>
                  ) : (
                    <span className="text-sm text-muted-foreground">
                      <Loader2 className="mr-1 inline size-3 animate-spin" />
                      评分中
                    </span>
                  )}
                  {item.attempt_id && item.status === "done" && (
                    <audio
                      controls
                      preload="none"
                      src={
                        item.attempt_id ? audioUrl(item.attempt_id) : undefined
                      }
                      className="h-8"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <track kind="captions" />
                    </audio>
                  )}
                </div>
              ))}
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}
