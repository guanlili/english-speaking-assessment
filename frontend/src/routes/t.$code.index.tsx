import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import {
  BookA,
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
import { useRef, useState } from "react"
import { toast } from "sonner"
import type { BoardStudent } from "@/client"
import { ApiError, ClassesService } from "@/client"
import AttemptAudio from "@/components/Practice/AttemptAudio"
import { AssignmentComposer } from "@/components/Teaching/AssignmentComposer"
import { ExerciseHistory } from "@/components/Teaching/ExerciseHistory"
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
import { downloadCsv } from "@/lib/csv"
import { type BiString, useI18n } from "@/lib/i18n"
import { ITEM_TYPE_LABELS, TERMS } from "@/lib/terms"

export const Route = createFileRoute("/t/$code/")({
  component: TeacherBoardPage,
  head: () => ({
    meta: [{ title: `课堂面板 / Class Dashboard - ${APP_NAME}` }],
  }),
})

// 有学生在评分中时的轮询间隔（PRD US-10：最后一人提交后 2 分钟内一致）
const PENDING_REFRESH_MS = 5000
// 无人评分时的基础同步间隔：面板提前打开也能发现后续提交/指派变化
const IDLE_REFRESH_MS = 20000

function TeacherBoardPage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/t/$code/" })
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<"prepare" | "results" | "history">(
    "prepare",
  )
  const [historyExerciseId, setHistoryExerciseId] = useState<string | null>(
    null,
  )
  const historyTabRef = useRef<HTMLButtonElement>(null)
  const viewHistory = (exerciseId: string | null) => {
    setHistoryExerciseId(exerciseId)
    setActiveTab("history")
    historyTabRef.current?.focus({ preventScroll: true })
    historyTabRef.current?.scrollIntoView({ block: "start" })
  }

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
        <span className="sr-only">
          {t({ zh: "正在加载课堂面板…", en: "Loading class dashboard…" })}
        </span>
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
          {t({
            zh: "你还不是这个课堂的授权教师，请让管理员在后台把你绑到这间课堂。",
            en: "You are not an owner teacher of this classroom yet. Ask an admin to link you to it in the admin console.",
          })}
          <Button variant="outline" asChild>
            <Link to="/">{t({ zh: "回首页", en: "Back to Home" })}</Link>
          </Button>
        </div>
      )
    }
    if (status !== 404) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-muted-foreground">
          {t({
            zh: "课堂面板加载失败，请稍后重试。",
            en: "Failed to load the class dashboard, please try again later.",
          })}
          <Button variant="outline" onClick={() => boardQuery.refetch()}>
            {t({ zh: "重试", en: "Retry" })}
          </Button>
        </div>
      )
    }
    return (
      <div className="space-y-6">
        <Link to="/classrooms" className="text-sm text-primary">
          ← {t({ zh: "我的课堂", en: "My Classrooms" })}
        </Link>
        <h1 className="text-2xl font-bold">
          {t({
            zh: `课堂 ${code}`,
            en: `Classroom ${code}`,
          })}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t({
            zh: "暂无可展示的练习结果。可先准备并安排课堂内容；若课堂已停用，请返回课堂列表核对。",
            en: "No practice results to show yet. Prepare and assign classroom content first; if the classroom is deactivated, check the classroom list.",
          })}
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

  const STATUS_LABELS: Record<string, BiString> = {
    all: { zh: "全部状态", en: "All statuses" },
    done: { zh: "已提交", en: "Submitted" },
    practicing: { zh: "评分中", en: "Scoring" },
    idle: { zh: "未提交", en: "Not submitted" },
    inactive: { zh: "7 天未练", en: "Inactive 7 days" },
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
      t({ zh: "姓名", en: "Name" }),
      t({ zh: "区分码", en: "Suffix" }),
      t({ zh: "完成题数", en: "Items Done" }),
      t({ zh: "跟读均分", en: "Repeat Avg" }),
      t({ zh: "情景问答均分", en: "Scenario Q&A Avg" }),
      "XP",
      t({ zh: "连胜天数", en: "Streak Days" }),
      t({ zh: "状态", en: "Status" }),
    ]
    const rows = filteredStudents.map((st) => [
      st.display_name,
      st.suffix ?? "",
      `${st.done_count ?? 0}/${st.total_count ?? 0}`,
      st.repeat_avg ?? "-",
      st.question_avg ?? "-",
      String(st.xp ?? 0),
      String(st.streak_days ?? 0),
      t(STATUS_LABELS[statusOf(st)] ?? { zh: "", en: "" }),
    ])
    downloadCsv(
      [header, ...rows],
      t({
        zh: `课堂${board.classroom_code}-练习名单-${new Date()
          .toISOString()
          .slice(0, 10)}.csv`,
        en: `classroom-${board.classroom_code}-practice-roster-${new Date()
          .toISOString()
          .slice(0, 10)}.csv`,
      }),
    )
  }

  const shareLink = async () => {
    const url = `${window.location.origin}/j/${board.classroom_code}`
    try {
      await navigator.clipboard.writeText(url)
      toast.success(
        t({ zh: "学生入口链接已复制", en: "Student entry link copied" }),
        {
          description: url,
        },
      )
    } catch (err) {
      console.error("Failed to copy share link:", err)
      toast.error(
        t({
          zh: "复制失败，请手动复制",
          en: "Copy failed — please copy manually",
        }),
        {
          description: url,
        },
      )
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
    const message = t({
      zh: `【${board.classroom_name}】${names || "同学们"}，请完成今天的口语练习。提交后老师会查看反馈。课堂码：${board.classroom_code}`,
      en: `[${board.classroom_name}] ${names || "everyone"}, please complete today's speaking practice. Your teacher will review your feedback after you submit. Classroom code: ${board.classroom_code}`,
    })
    try {
      await navigator.clipboard.writeText(message)
      toast.success(t({ zh: "提醒文案已复制", en: "Reminder text copied" }), {
        description: message,
      })
    } catch (error) {
      console.error("Failed to copy reminder:", error)
      toast.error(
        t({ zh: "复制失败，请重试", en: "Copy failed, please try again" }),
      )
    }
  }

  return (
    <div className="bg-background">
      <div className="flex w-full flex-col gap-6">
        <Link to="/classrooms" className="text-sm font-medium text-primary">
          ← {t({ zh: "我的课堂", en: "My Classrooms" })}
        </Link>
        <div className="flex items-start justify-between gap-4 rounded-2xl border border-primary/10 bg-secondary/40 p-5 sm:p-7">
          <div className="min-w-0">
            <p className="mb-2 text-[10px] font-semibold tracking-[0.18em] text-primary">
              CLASSROOM STUDIO
            </p>
            <h1 className="break-words text-2xl font-semibold tracking-tight sm:text-3xl">
              {board.classroom_name}
              {board.current_exercise?.is_exam && (
                <Badge variant="destructive" className="ml-2 align-middle">
                  {t({ zh: "模考", en: "Exam" })} ·{" "}
                  {board.current_exercise.time_limit_minutes}
                  {t({ zh: " 分钟", en: " min" })}
                </Badge>
              )}
            </h1>
            <p className="text-sm text-muted-foreground">
              {board.classroom_grade && `${board.classroom_grade} · `}
              {t({
                zh: `课堂码 ${board.classroom_code} · 已提交 ${board.submitted_count}/${board.class_size}`,
                en: `Classroom code ${board.classroom_code} · Submitted ${board.submitted_count}/${board.class_size}`,
              })}
              {board.pending_count > 0 && (
                <span className="ml-2 inline-flex items-center gap-1">
                  <Loader2 className="size-3 animate-spin" />
                  {t({
                    zh: `${board.pending_count} 人评分中`,
                    en: `${board.pending_count} scoring`,
                  })}
                </span>
              )}
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {board.teaching_goal && (
                <Badge variant="secondary">
                  {t({
                    zh: `目标：${board.teaching_goal}`,
                    en: `Goal: ${board.teaching_goal}`,
                  })}
                </Badge>
              )}
              <Badge variant="secondary">
                {t({ zh: "评分引擎：", en: "Scoring engine: " })}
                {board.engine === "volc_flash"
                  ? t({ zh: "豆包语音（AI）", en: "Doubao Speech (AI)" })
                  : board.engine === "ark"
                    ? t({ zh: "方舟（AI）", en: "Ark (AI)" })
                    : t({ zh: "演示模式", en: "Demo mode" })}
              </Badge>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link to="/t/$code/vocab" params={{ code }}>
                <BookA />
                {t(TERMS.vocabLearning)}
              </Link>
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => boardQuery.refetch()}
              disabled={boardQuery.isFetching}
            >
              <RefreshCw
                className={boardQuery.isFetching ? "animate-spin" : ""}
              />
              {t({ zh: "刷新", en: "Refresh" })}
            </Button>
          </div>
        </div>

        <Tabs
          value={activeTab}
          onValueChange={(value) => {
            if (
              value === "prepare" ||
              value === "results" ||
              value === "history"
            ) {
              setActiveTab(value)
            }
          }}
          className="gap-6"
        >
          <TabsList className="h-11">
            <TabsTrigger value="prepare" className="px-4 sm:px-6">
              {t({ zh: "练习安排", en: "Assign Practice" })}
            </TabsTrigger>
            <TabsTrigger value="results" className="px-4 sm:px-6">
              {t({ zh: "学生结果", en: "Student Results" })}
            </TabsTrigger>
            <TabsTrigger
              ref={historyTabRef}
              value="history"
              className="px-4 sm:px-6"
            >
              {t({ zh: "发布历史", en: "Publish History" })}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="prepare">
            <AssignmentComposer
              code={code}
              assignment={board.assignment}
              assignedItems={board.assigned_items}
              currentExercise={board.current_exercise}
              onViewHistory={viewHistory}
            />
          </TabsContent>
          <TabsContent value="results" className="space-y-6">
            {board.current_exercise && (
              <div className="space-y-2 rounded-xl border bg-card p-4 text-sm">
                <p className="font-semibold">
                  {t({
                    zh: `今日 · v${board.current_exercise.version_no} · ${board.current_exercise.title}`,
                    en: `Today · v${board.current_exercise.version_no} · ${board.current_exercise.title}`,
                  })}
                </p>
                <p className="text-muted-foreground">
                  {t({
                    zh: "此面板仅统计今日当前发布版本。重新发布后，旧版本的作答仍保存在发布历史中，未计入当前版本不代表成绩丢失。",
                    en: "This panel shows today's current published version only. Earlier answers remain in Publish History after republishing; they are not included in this version's results.",
                  })}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  className="min-h-11"
                  onClick={() => viewHistory(null)}
                >
                  {t({ zh: "查看历史版本结果", en: "View earlier results" })}
                </Button>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Card>
                <CardContent className="py-4">
                  <p className="text-xs text-muted-foreground">
                    {t({ zh: "班级学生", en: "Students" })}
                  </p>
                  <p className="mt-1 text-2xl font-bold">
                    {board.students.length}
                    <span className="ml-1 text-xs font-normal text-muted-foreground">
                      {t({
                        zh: `/ ${board.class_size} 人`,
                        en: `/ ${board.class_size}`,
                      })}
                    </span>
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="py-4">
                  <p className="text-xs text-muted-foreground">
                    {t({ zh: "已有作答", en: "Students with answers" })}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t({
                      zh: "至少提交一道题",
                      en: "At least one answer submitted",
                    })}
                  </p>
                  <p className="mt-1 text-2xl font-bold">
                    {board.submitted_count}
                    <span className="ml-1 text-xs font-normal text-muted-foreground">
                      {t({
                        zh: `/ ${board.class_size} 人`,
                        en: `/ ${board.class_size}`,
                      })}
                    </span>
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="py-4">
                  <p className="text-xs text-muted-foreground">
                    {t({ zh: "问答参考均分", en: "Scenario Q&A Avg" })}
                  </p>
                  <p className="mt-1 text-2xl font-bold">{classAvg}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="py-4">
                  <p className="text-xs text-muted-foreground">
                    {t({ zh: "值得关注", en: "Needs Attention" })}
                  </p>
                  <p className="mt-1 text-2xl font-bold">
                    {inactiveCount}
                    <span className="ml-1 text-xs font-normal text-muted-foreground">
                      {t({
                        zh: "人 7 天未练",
                        en: "inactive for 7 days",
                      })}
                    </span>
                  </p>
                </CardContent>
              </Card>
            </div>

            <Card className="border-primary/20 bg-secondary/30">
              <CardContent className="flex flex-wrap items-center gap-3 py-4">
                <div className="mr-auto min-w-48">
                  <p className="flex items-center gap-1.5 text-sm font-semibold">
                    <ClipboardCheck className="size-4 text-primary" />{" "}
                    {t({ zh: "教学动作", en: "Teaching Actions" })}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {attentionStudents.length > 0
                      ? t({
                          zh: `有 ${attentionStudents.length} 位学生还没完成本轮。`,
                          en: `${attentionStudents.length} student(s) haven't finished this round.`,
                        })
                      : t({
                          zh: "本轮已全部提交，可以进入下一次安排。",
                          en: "Everyone has submitted this round — ready for the next assignment.",
                        })}
                  </p>
                </div>
                {attentionStudents.length > 0 && (
                  <Button variant="outline" size="sm" onClick={copyReminder}>
                    <MessageCircle />{" "}
                    {t({ zh: "复制提醒文案", en: "Copy Reminder" })}
                  </Button>
                )}
                <Button size="sm" onClick={() => setActiveTab("prepare")}>
                  {t({ zh: "安排下一次练习", en: "Assign Next Practice" })}
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  {t({ zh: "今日名单", en: "Today's Roster" })}
                </CardTitle>
                <CardDescription>
                  {t({
                    zh: "点击一行展开每题分数和音频。分数是参考反馈，不是考试成绩。",
                    en: "Click a row to expand per-item scores and audio. Scores are reference feedback, not exam grades.",
                  })}
                  <span className="mt-1 block sm:hidden">
                    {t({
                      zh: "横向滑动表格，可以查看完整成绩与状态。",
                      en: "Swipe the table sideways to see all scores and statuses.",
                    })}
                  </span>
                </CardDescription>
              </CardHeader>
              <CardContent className="pb-0">
                <div className="flex flex-wrap items-center gap-2 pb-3">
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    aria-label={t({
                      zh: "练习状态筛选",
                      en: "Filter by practice status",
                    })}
                    className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground transition-colors hover:border-primary/35"
                  >
                    {Object.entries(STATUS_LABELS).map(([v, label]) => (
                      <option key={v} value={v}>
                        {t(label)}
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
                      placeholder={t({
                        zh: "搜索学生姓名",
                        en: "Search student names",
                      })}
                      aria-label={t({
                        zh: "搜索学生姓名",
                        en: "Search student names",
                      })}
                      className="pl-9"
                    />
                  </div>
                  <span role="status" className="text-xs text-muted-foreground">
                    {t({
                      zh: `${filteredStudents.length} / ${board.students.length} 人`,
                      en: `${filteredStudents.length} / ${board.students.length}`,
                    })}
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
                      {t({ zh: "清除筛选", en: "Clear Filters" })}
                    </Button>
                  )}
                  <div className="ml-auto flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void shareLink()}
                    >
                      <Link2 />
                      {t({ zh: "学生入口", en: "Student Entry" })}
                    </Button>
                    <Button variant="outline" size="sm" onClick={exportCsv}>
                      <Download />
                      {t({ zh: "导出", en: "Export" })}
                    </Button>
                  </div>
                </div>
              </CardContent>
              <CardContent>
                {!hasStudents ? (
                  <p className="py-8 text-center text-muted-foreground">
                    {t({
                      zh: "还没有学生进入这个课堂。",
                      en: "No students have joined this classroom yet.",
                    })}
                  </p>
                ) : filteredStudents.length === 0 ? (
                  <div className="flex flex-col items-center gap-3 rounded-2xl bg-background px-4 py-10 text-center">
                    <Search
                      className="size-7 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <p className="text-sm font-semibold">
                      {t({
                        zh: "没有找到符合条件的学生",
                        en: "No matching students",
                      })}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {t({
                        zh: "试试其他姓名，或清除筛选查看全部学生。",
                        en: "Try another name, or clear filters to see all students.",
                      })}
                    </p>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setNameQuery("")
                        setStatusFilter("all")
                      }}
                    >
                      {t({ zh: "查看全部学生", en: "View All Students" })}
                    </Button>
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-8" />
                        <TableHead>{t({ zh: "姓名", en: "Name" })}</TableHead>
                        <TableHead>{t({ zh: "完成", en: "Done" })}</TableHead>
                        <TableHead>
                          {t({
                            zh: "跟读参考分",
                            en: "Repeat Reference Score",
                          })}
                        </TableHead>
                        <TableHead>
                          {t({
                            zh: "问答参考分",
                            en: "Scenario Q&A Reference Score",
                          })}
                        </TableHead>
                        <TableHead>{t({ zh: "状态", en: "Status" })}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredStudents.map((student) => (
                        <StudentRow
                          key={student.student_id}
                          student={student}
                          code={code}
                          isExamPublish={
                            board.current_exercise?.is_exam === true
                          }
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
                  <Sparkles className="size-4" />{" "}
                  {t({
                    zh: "下一次课堂，可以这样开始",
                    en: "Start your next class like this",
                  })}
                </p>
                <p className="mt-1 text-xs text-accent-foreground/80">
                  {t({
                    zh: "让学生分享「今天最想再说一次的句子」。先发现一个亮点，再给一个能做到的小建议。",
                    en: 'Ask students to share "the sentence I\'d most like to say again today". Spot one highlight first, then give one small, doable suggestion.',
                  })}
                </p>
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="history">
            <ExerciseHistory
              key={historyExerciseId ?? "history-list"}
              code={code}
              initialExerciseId={historyExerciseId}
            />
          </TabsContent>
        </Tabs>
        <p className="pb-6 text-center text-xs text-muted-foreground">
          {t({
            zh: "数据在评分完成后出现；有「评分中」时页面每几秒自动刷新。参考数据辅助教学，不定义学生。",
            en: "Data appears once scoring finishes; while items are scoring, the page refreshes every few seconds. Reference data supports teaching — it doesn't define students.",
          })}
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
  isExamPublish,
}: {
  student: BoardStudent
  code: string
  expanded: boolean
  onToggle: () => void
  isExamPublish: boolean
}) {
  const { t } = useI18n()
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
              expanded
                ? t({
                    zh: `收起 ${name} 的详情`,
                    en: `Collapse details for ${name}`,
                  })
                : t({
                    zh: `展开 ${name} 的详情`,
                    en: `Expand details for ${name}`,
                  })
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
          {isExamPublish && (
            <Badge
              variant={student.exam_tab_switches ? "destructive" : "outline"}
            >
              {student.exam_tab_switches === null || undefined
                ? t({ zh: "未开考", en: "Not started" })
                : `${t({ zh: "切屏", en: "Switches" })} ${student.exam_tab_switches}`}
            </Badge>
          )}
          {isExamPublish && student.exam_time_used_seconds != null && (
            <Badge variant="secondary">
              {student.exam_ended
                ? `${t({ zh: "已交卷", en: "Submitted" })} · ${formatExamUsed(student.exam_time_used_seconds)}`
                : `${t({ zh: "用时", en: "Elapsed" })} ${formatExamUsed(student.exam_time_used_seconds)}`}
            </Badge>
          )}
          {student.inactive_days7 && (
            <Badge variant="destructive">
              {t({ zh: "7 日未练", en: "Inactive 7 Days" })}
            </Badge>
          )}
          {student.has_pending ? (
            <Badge variant="secondary">
              {t({ zh: "评分中", en: "Scoring" })}
            </Badge>
          ) : student.done_count === 0 ? (
            <span className="text-muted-foreground">
              {t({ zh: "未提交", en: "Not submitted" })}
            </span>
          ) : (
            <Badge variant="outline">
              {t({ zh: "已提交", en: "Submitted" })}
            </Badge>
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
                      {t({
                        zh: "查看进步轨迹 →",
                        en: "View Progress Trail →",
                      })}
                    </Link>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={async (event) => {
                      event.stopPropagation()
                      const feedback =
                        student.done_count === 0
                          ? t({
                              zh: `${name} 还没有提交本轮口语练习，可以提醒完成。`,
                              en: `${name} hasn't submitted this round of speaking practice yet — a reminder could help.`,
                            })
                          : t({
                              zh: `${name} 已完成 ${student.done_count}/${student.total_count} 题，可结合结果页逐题反馈。`,
                              en: `${name} has completed ${student.done_count}/${student.total_count} items; give per-item feedback from the results view.`,
                            })
                      try {
                        await navigator.clipboard.writeText(feedback)
                        toast.success(
                          t({
                            zh: "反馈文案已复制",
                            en: "Feedback text copied",
                          }),
                          {
                            description: feedback,
                          },
                        )
                      } catch (error) {
                        console.error("Failed to copy feedback:", error)
                        toast.error(
                          t({
                            zh: "复制失败，请重试",
                            en: "Copy failed, please try again",
                          }),
                        )
                      }
                    }}
                  >
                    {t({ zh: "复制反馈", en: "Copy Feedback" })}
                  </Button>
                </div>
              </div>
              {student.items
                .filter((i) => i.type !== "instruction")
                .every((i) => i.status === "missing") && (
                <p className="text-sm text-muted-foreground">
                  {t({ zh: "还没有作答。", en: "No answers yet." })}
                </p>
              )}
              {student.items.map((item, index) => (
                <div
                  key={item.item_id}
                  className="flex flex-wrap items-center gap-3 rounded-md border px-3 py-2"
                >
                  <span className="w-20 text-sm text-muted-foreground">
                    {index + 1}.{" "}
                    {t(
                      ITEM_TYPE_LABELS[item.type] ?? {
                        zh: item.type,
                        en: item.type,
                      },
                    )}
                  </span>
                  {item.type === "instruction" ? (
                    item.status === "done" ? (
                      <span className="text-sm font-medium text-primary">
                        {t({ zh: "已读", en: "Read" })}
                      </span>
                    ) : (
                      <span className="text-sm text-muted-foreground">
                        {t({ zh: "未读", en: "Unread" })}
                      </span>
                    )
                  ) : item.status === "missing" ? (
                    <span className="text-sm text-muted-foreground">
                      {t({ zh: "未做", en: "Missing" })}
                    </span>
                  ) : item.status === "done" ? (
                    <span className="text-sm font-semibold tabular-nums">
                      {t(TERMS.score)} {item.overall ?? "–"}
                    </span>
                  ) : item.status === "failed" ? (
                    <span className="text-sm text-destructive">
                      {t({ zh: "未评出", en: "No Score" })}
                    </span>
                  ) : (
                    <span className="text-sm text-muted-foreground">
                      <Loader2 className="mr-1 inline size-3 animate-spin" />
                      {t({ zh: "评分中", en: "Scoring" })}
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

function formatExamUsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, "0")}`
}
