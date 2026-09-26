import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronRight,
  Download,
  Link2,
  Loader2,
  RefreshCw,
  Sparkles,
  Target,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
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

  const [statusFilter, setStatusFilter] = useState("all")
  const [nameQuery, setNameQuery] = useState("")
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

  const statusOf = (st: BoardStudent) =>
    st.inactive_days7
      ? "inactive"
      : st.has_pending
        ? "practicing"
        : (st.done_count ?? 0) > 0
          ? "done"
          : "idle"

  const STATUS_LABELS: Record<string, string> = {
    all: "全部状态",
    done: "已完成",
    practicing: "评分中",
    idle: "未提交",
    inactive: "7 天未练",
  }

  const filteredStudents = board.students.filter((st) => {
    if (statusFilter !== "all" && statusOf(st) !== statusFilter) return false
    if (
      nameQuery &&
      !st.display_name.toLowerCase().includes(nameQuery.toLowerCase())
    )
      return false
    return true
  })

  const scored = board.students.filter(
    (st) => st.question_avg !== null && st.question_avg !== undefined,
  )
  const classAvg = scored.length
    ? (
        scored.reduce((acc, st) => acc + (st.question_avg ?? 0), 0) /
        scored.length
      ).toFixed(1)
    : "-"
  const inactiveCount = board.students.filter((st) => st.inactive_days7).length

  const exportCsv = () => {
    const header = [
      "姓名",
      "区分码",
      "当前档",
      "完成题数",
      "跟读均分",
      "问答均分",
      "XP",
      "连胜天数",
      "状态",
    ]
    const rows = filteredStudents.map((st) => [
      st.display_name,
      st.suffix ?? "",
      st.current_band ?? "",
      `${st.done_count ?? 0}/${st.total_count ?? 0}`,
      st.repeat_avg ?? "-",
      st.question_avg ?? "-",
      String(st.xp ?? 0),
      String(st.streak_days ?? 0),
      STATUS_LABELS[statusOf(st)] ?? "",
    ])
    const quoteCell = (v: string) => `"${v.replace(/"/g, '""')}"`
    const csv =
      "\uFEFF" +
      [header, ...rows]
        .map((r) => r.map((c) => quoteCell(String(c))).join(","))
        .join("\r\n")
    const url = URL.createObjectURL(
      new Blob([csv], { type: "text/csv;charset=utf-8" }),
    )
    const link = document.createElement("a")
    link.href = url
    link.download = `课堂${board.classroom_code}-练习名单-${new Date()
      .toISOString()
      .slice(0, 10)}.csv`
    document.body.append(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  const shareLink = async () => {
    const url = `${window.location.origin}/j/${board.classroom_code}`
    try {
      await navigator.clipboard.writeText(url)
      toast.success("学生入口链接已复制", { description: url })
    } catch {
      toast.error("复制失败，请手动复制", { description: url })
    }
  }

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
            <div className="mt-1.5 grid max-w-xs gap-1">
              {Object.entries(board.band_distribution).map(([band, count]) => {
                const max = Math.max(
                  1,
                  ...Object.values(board.band_distribution),
                )
                return (
                  <div
                    key={band}
                    className="grid grid-cols-[80px_1fr_30px] items-center gap-2 text-[11px]"
                  >
                    <span className="text-muted-foreground">{band}</span>
                    <div className="h-1.5 overflow-hidden rounded-full bg-background">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${(count / max) * 100}%` }}
                      />
                    </div>
                    <span className="text-right tabular-nums">{count}</span>
                  </div>
                )
              })}
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

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Card>
            <CardContent className="py-4">
              <p className="text-xs text-muted-foreground">班级学生</p>
              <p className="mt-1 text-2xl font-bold">
                {board.students.length}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  / {board.class_size} 人
                </span>
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="py-4">
              <p className="text-xs text-muted-foreground">今日完成</p>
              <p className="mt-1 text-2xl font-bold">
                {board.submitted_count}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  / {board.class_size} 人
                </span>
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="py-4">
              <p className="text-xs text-muted-foreground">班级问答均分</p>
              <p className="mt-1 text-2xl font-bold">{classAvg}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="py-4">
              <p className="text-xs text-muted-foreground">值得关注</p>
              <p className="mt-1 text-2xl font-bold">
                {inactiveCount}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  人 7 天未练
                </span>
              </p>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">今日名单</CardTitle>
            <CardDescription>
              点击一行展开每题分数和音频。分数是参考反馈，不是考试成绩。
            </CardDescription>
          </CardHeader>
          <CardContent className="pb-0">
            <div className="flex flex-wrap items-center gap-2 pb-3">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                aria-label="练习状态筛选"
                className="h-9 rounded-lg border border-border bg-card px-2 text-xs text-muted-foreground"
              >
                {Object.entries(STATUS_LABELS).map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </select>
              <input
                value={nameQuery}
                onChange={(e) => setNameQuery(e.target.value)}
                placeholder="搜索学生姓名"
                aria-label="搜索学生姓名"
                className="h-9 rounded-lg border border-border bg-card px-3 text-xs"
              />
              <span className="text-xs text-muted-foreground">
                {filteredStudents.length} 人
              </span>
              <div className="ml-auto flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void shareLink()}
                >
                  <Link2 />
                  学生入口
                </Button>
                <Button variant="outline" size="sm" onClick={exportCsv}>
                  <Download />
                  导出
                </Button>
              </div>
            </div>
          </CardContent>
          <CardContent>
            {!hasStudents ? (
              <p className="py-8 text-center text-muted-foreground">
                还没有学生进入这个课堂。
              </p>
            ) : filteredStudents.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                没有符合筛选条件的学生。
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
                  {filteredStudents.map((student) => (
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

        <Card className="border-accent bg-accent">
          <CardContent className="py-4">
            <p className="flex items-center gap-1.5 text-sm font-semibold">
              <Sparkles className="size-4" /> 下一次课堂，可以这样开始
            </p>
            <p className="mt-1 text-xs text-accent-foreground/80">
              让学生分享「今天最想再说一次的句子」。先发现一个亮点，再给一个能做到的小建议。
            </p>
          </CardContent>
        </Card>

        <p className="pb-6 text-center text-xs text-muted-foreground">
          数据在评分完成后出现；有「评分中」时页面每几秒自动刷新。参考数据辅助教学，不定义学生。
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
