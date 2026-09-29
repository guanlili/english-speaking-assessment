import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Download,
  Link2,
  Loader2,
  MessageCircle,
  RefreshCw,
  Search,
  Sparkles,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { BoardStudent } from "@/client"
import { ApiError, ClassesService } from "@/client"
import AttemptAudio from "@/components/Practice/AttemptAudio"
import { AssignmentComposer } from "@/components/Teaching/AssignmentComposer"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { APP_NAME } from "@/config"

export const Route = createFileRoute("/t/$code/")({
  component: TeacherBoardPage,
  head: () => ({
    meta: [{ title: `课堂面板 - ${APP_NAME}` }],
  }),
})

const TYPE_LABELS: Record<string, string> = {
  passage: "文章朗读",
  repeat: "听句复述",
  question: "情景问答",
}

// 有学生在评分中时的轮询间隔（PRD US-10：最后一人提交后 2 分钟内一致）
const PENDING_REFRESH_MS = 5000
// 无人评分时的基础同步间隔：面板提前打开也能发现后续提交/指派变化
const IDLE_REFRESH_MS = 20000

function TeacherBoardPage() {
  const { code } = useParams({ from: "/t/$code/" })
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<"prepare" | "results">("prepare")

  const [statusFilter, setStatusFilter] = useState("all")
  const [nameQuery, setNameQuery] = useState("")
  const boardQuery = useQuery({
    queryKey: ["teacher", "board", code],
    queryFn: () => ClassesService.readClassBoard({ code: code.toUpperCase() }),
    refetchInterval: (query) =>
      (query.state.data?.pending_count ?? 0) > 0
        ? PENDING_REFRESH_MS
        : IDLE_REFRESH_MS,
  })

  if (boardQuery.isPending) {
    return (
      <div role="status" className="space-y-6">
        <span className="sr-only">正在加载课堂面板…</span>
        <Skeleton className="h-40 rounded-2xl" />
        <Skeleton className="h-11 w-64 rounded-xl" />
        <Skeleton className="h-80 rounded-2xl" />
      </div>
    )
  }
  if (boardQuery.isError || !boardQuery.data) {
    const status =
      boardQuery.error instanceof ApiError ? boardQuery.error.status : undefined
    // 401 由全局处理器跳登录；403 = 已登录但不是本课授权教师，不登出
    if (status === 403) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-muted-foreground">
          你还不是这个课堂的授权教师，请让管理员在后台把你绑到这间课堂。
          <Button variant="outline" asChild>
            <Link to="/">回首页</Link>
          </Button>
        </div>
      )
    }
    if (status !== 404) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-muted-foreground">
          课堂面板加载失败，请稍后重试。
          <Button variant="outline" onClick={() => boardQuery.refetch()}>
            重试
          </Button>
        </div>
      )
    }
    return (
      <div className="space-y-6">
        <Link to="/classrooms" className="text-sm text-primary">
          ← 我的课堂
        </Link>
        <h1 className="text-2xl font-bold">课堂 {code}</h1>
        <p className="text-sm text-muted-foreground">
          暂无可展示的练习结果。可先准备并安排课堂内容；若课堂已停用，请返回课堂列表核对。
        </p>
        <AssignmentComposer code={code} />
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
    done: "已提交",
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
      "完成题数",
      "跟读均分",
      "情景问答均分",
      "XP",
      "连胜天数",
      "状态",
    ]
    const rows = filteredStudents.map((st) => [
      st.display_name,
      st.suffix ?? "",
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
    } catch (err) {
      console.error("Failed to copy share link:", err)
      toast.error("复制失败，请手动复制", { description: url })
    }
  }

  const attentionStudents = board.students.filter(
    (student) => student.inactive_days7 || student.done_count === 0,
  )

  const copyReminder = async () => {
    const names = attentionStudents
      .map((student) => student.display_name)
      .slice(0, 8)
      .join("、")
    const message = `【${board.classroom_name}】${names || "同学们"}，请完成今天的口语练习。提交后老师会查看反馈。课堂码：${board.classroom_code}`
    try {
      await navigator.clipboard.writeText(message)
      toast.success("提醒文案已复制", { description: message })
    } catch (error) {
      console.error("Failed to copy reminder:", error)
      toast.error("复制失败，请重试")
    }
  }

  return (
    <div className="bg-background">
      <div className="flex w-full flex-col gap-6">
        <Link to="/classrooms" className="text-sm font-medium text-primary">
          ← 我的课堂
        </Link>
        <div className="flex items-start justify-between gap-4 rounded-2xl border border-primary/10 bg-secondary/40 p-5 sm:p-7">
          <div className="min-w-0">
            <p className="mb-2 text-[10px] font-semibold tracking-[0.18em] text-primary">
              CLASSROOM STUDIO
            </p>
            <h1 className="break-words text-2xl font-semibold tracking-tight sm:text-3xl">
              {board.classroom_name}
            </h1>
            <p className="text-sm text-muted-foreground">
              {board.classroom_grade && `${board.classroom_grade} · `}
              课堂码 {board.classroom_code} · 已提交 {board.submitted_count}/
              {board.class_size}
              {board.pending_count > 0 && (
                <span className="ml-2 inline-flex items-center gap-1">
                  <Loader2 className="size-3 animate-spin" />
                  {board.pending_count} 人评分中
                </span>
              )}
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {board.teaching_goal && (
                <Badge variant="secondary">目标：{board.teaching_goal}</Badge>
              )}
              <Badge variant="secondary">
                评分引擎：
                {board.engine === "volc_flash"
                  ? "豆包语音（AI）"
                  : board.engine === "ark"
                    ? "方舟（AI）"
                    : "演示模式"}
              </Badge>
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

        <Tabs
          value={activeTab}
          onValueChange={(value) => {
            if (value === "prepare" || value === "results") setActiveTab(value)
          }}
          className="gap-6"
        >
          <TabsList className="h-11">
            <TabsTrigger value="prepare" className="px-6">
              练习安排
            </TabsTrigger>
            <TabsTrigger value="results" className="px-6">
              学生结果
            </TabsTrigger>
          </TabsList>
          <TabsContent value="prepare">
            <AssignmentComposer
              code={code}
              assignment={board.assignment}
              assignedItems={board.assigned_items}
              currentExercise={board.current_exercise}
            />
          </TabsContent>
          <TabsContent value="results" className="space-y-6">
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
                  <p className="text-xs text-muted-foreground">问答参考均分</p>
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

            <Card className="border-primary/20 bg-secondary/30">
              <CardContent className="flex flex-wrap items-center gap-3 py-4">
                <div className="mr-auto min-w-48">
                  <p className="flex items-center gap-1.5 text-sm font-semibold">
                    <ClipboardCheck className="size-4 text-primary" /> 教学动作
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {attentionStudents.length > 0
                      ? `有 ${attentionStudents.length} 位学生还没完成本轮。`
                      : "本轮已全部提交，可以进入下一次安排。"}
                  </p>
                </div>
                {attentionStudents.length > 0 && (
                  <Button variant="outline" size="sm" onClick={copyReminder}>
                    <MessageCircle /> 复制提醒文案
                  </Button>
                )}
                <Button size="sm" onClick={() => setActiveTab("prepare")}>
                  安排下一次练习
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">今日名单</CardTitle>
                <CardDescription>
                  点击一行展开每题分数和音频。分数是参考反馈，不是考试成绩。
                  <span className="mt-1 block sm:hidden">
                    横向滑动表格，可以查看完整成绩与状态。
                  </span>
                </CardDescription>
              </CardHeader>
              <CardContent className="pb-0">
                <div className="flex flex-wrap items-center gap-2 pb-3">
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    aria-label="练习状态筛选"
                    className="h-11 rounded-xl border border-input bg-card px-3 text-sm text-foreground transition-colors hover:border-primary/35"
                  >
                    {Object.entries(STATUS_LABELS).map(([v, label]) => (
                      <option key={v} value={v}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <div className="relative min-w-40 flex-1 sm:max-w-64">
                    <Search
                      aria-hidden="true"
                      className="pointer-events-none absolute left-3 top-3.5 size-4 text-muted-foreground"
                    />
                    <Input
                      type="search"
                      value={nameQuery}
                      onChange={(e) => setNameQuery(e.target.value)}
                      placeholder="搜索学生姓名"
                      aria-label="搜索学生姓名"
                      className="pl-9"
                    />
                  </div>
                  <span role="status" className="text-xs text-muted-foreground">
                    {filteredStudents.length} / {board.students.length} 人
                  </span>
                  {(nameQuery || statusFilter !== "all") && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setNameQuery("")
                        setStatusFilter("all")
                      }}
                    >
                      清除筛选
                    </Button>
                  )}
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
                  <div className="flex flex-col items-center gap-3 rounded-2xl bg-background px-4 py-10 text-center">
                    <Search
                      className="size-7 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <p className="text-sm font-semibold">
                      没有找到符合条件的学生
                    </p>
                    <p className="text-xs text-muted-foreground">
                      试试其他姓名，或清除筛选查看全部学生。
                    </p>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setNameQuery("")
                        setStatusFilter("all")
                      }}
                    >
                      查看全部学生
                    </Button>
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-8" />
                        <TableHead>姓名</TableHead>
                        <TableHead>完成</TableHead>
                        <TableHead>跟读参考分</TableHead>
                        <TableHead>问答参考分</TableHead>
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
          </TabsContent>
        </Tabs>
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
          <button
            type="button"
            aria-expanded={expanded}
            aria-label={
              expanded ? `收起 ${name} 的详情` : `展开 ${name} 的详情`
            }
            onClick={(e) => {
              e.stopPropagation()
              onToggle()
            }}
            className="grid size-9 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-primary"
          >
            {expanded ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </button>
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
            <Badge variant="outline">已提交</Badge>
          )}
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow>
          <TableCell colSpan={6}>
            {/* biome-ignore lint/a11y/noStaticElementInteractions: stop click bubbling to row toggle */}
            <div
              className="space-y-2 py-1"
              onMouseDown={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between">
                <div className="flex flex-wrap gap-2">
                  <Button variant="link" size="sm" asChild>
                    <Link
                      to="/t/$code/s/$studentId"
                      params={{ code, studentId: student.student_id }}
                    >
                      查看进步轨迹 →
                    </Link>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={async (event) => {
                      event.stopPropagation()
                      const feedback =
                        student.done_count === 0
                          ? `${name} 还没有提交本轮口语练习，可以提醒完成。`
                          : `${name} 已完成 ${student.done_count}/${student.total_count} 题，可结合结果页逐题反馈。`
                      try {
                        await navigator.clipboard.writeText(feedback)
                        toast.success("反馈文案已复制", {
                          description: feedback,
                        })
                      } catch (error) {
                        console.error("Failed to copy feedback:", error)
                        toast.error("复制失败，请重试")
                      }
                    }}
                  >
                    复制反馈
                  </Button>
                </div>
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
                      参考分 {item.overall ?? "–"}
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
                    <AttemptAudio attemptId={item.attempt_id} className="h-8" />
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
