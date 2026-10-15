import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import {
  ArrowLeft,
  BookA,
  ClipboardList,
  History,
  Loader2,
  RefreshCw,
  Sparkles,
  Users,
} from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { ApiError, ClassesService } from "@/client"
import { AssignmentComposer } from "@/components/Teaching/AssignmentComposer"
import { BoardRosterCard } from "@/components/Teaching/BoardRosterCard"
import { BoardStatsCards } from "@/components/Teaching/BoardStatsCards"
import { BoardTeachingActions } from "@/components/Teaching/BoardTeachingActions"
import { ClassroomIssues } from "@/components/Teaching/ClassroomIssues"
import { ExerciseHistory } from "@/components/Teaching/ExerciseHistory"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { APP_NAME } from "@/config"
import {
  boardReminderMessage,
  boardRosterCsv,
  boardStatusOf,
  needsAttentionStudents,
} from "@/lib/board-copy"
import { copyText } from "@/lib/clipboard"
import { downloadCsv } from "@/lib/csv"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"

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

  const filteredStudents = board.students.filter((st) => {
    if (statusFilter !== "all" && boardStatusOf(st) !== statusFilter) {
      return false
    }
    if (
      nameQuery &&
      !st.display_name.toLowerCase().includes(nameQuery.toLowerCase())
    ) {
      return false
    }
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
  const attentionStudents = needsAttentionStudents(board.students)

  const clearFilters = () => {
    setNameQuery("")
    setStatusFilter("all")
  }
  const toggleRow = (studentId: string) => {
    setExpandedId(expandedId === studentId ? null : studentId)
  }

  const exportCsv = () => {
    const { rows, filename } = boardRosterCsv(
      filteredStudents,
      board.classroom_code,
      t,
    )
    downloadCsv(rows, filename)
  }

  const shareLink = async () => {
    const url = `${window.location.origin}/j/${board.classroom_code}`
    if (await copyText(url)) {
      toast.success(
        t({ zh: "学生入口链接已复制", en: "Student entry link copied" }),
        {
          description: url,
        },
      )
    } else {
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

  const copyReminder = async () => {
    const message = boardReminderMessage(board, board.students, t)
    if (await copyText(message)) {
      toast.success(t({ zh: "提醒文案已复制", en: "Reminder text copied" }), {
        description: message,
      })
    } else {
      toast.error(
        t({ zh: "复制失败，请重试", en: "Copy failed, please try again" }),
      )
    }
  }

  return (
    <div className="bg-background">
      <div className="flex w-full min-w-0 flex-col gap-5 sm:gap-6">
        <Link
          to="/classrooms"
          className="inline-flex min-h-11 w-fit items-center gap-2 text-sm font-medium text-muted-foreground transition-colors hover:text-primary"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          {t({ zh: "我的课堂", en: "My Classrooms" })}
        </Link>
        <div className="relative isolate flex flex-col justify-between gap-6 overflow-hidden rounded-3xl bg-brand-pine p-6 text-paper-hero sm:p-8 lg:flex-row lg:items-center">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -right-16 -top-24 -z-10 size-80 rounded-full border border-white/10"
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -bottom-44 right-20 -z-10 size-80 rounded-full border border-white/10"
          />
          <div className="min-w-0 space-y-3">
            <p className="text-xs font-medium tracking-widest text-paper-hero/70">
              {t({ zh: "课堂教学", en: "CLASSROOM STUDIO" })}
            </p>
            <h1 className="break-words text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">
              {board.classroom_name}
              {board.current_exercise?.is_exam && (
                <Badge variant="destructive" className="ml-2 align-middle">
                  {t({ zh: "模考", en: "Exam" })} ·{" "}
                  {board.current_exercise.time_limit_minutes}
                  {t({ zh: " 分钟", en: " min" })}
                </Badge>
              )}
            </h1>
            <p className="text-sm leading-6 text-paper-hero/80">
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
            <div className="flex flex-wrap gap-2">
              {board.teaching_goal && (
                <Badge
                  variant="secondary"
                  className="max-w-full whitespace-normal border-white/10 bg-white/10 text-paper-hero"
                >
                  {t({
                    zh: `目标：${board.teaching_goal}`,
                    en: `Goal: ${board.teaching_goal}`,
                  })}
                </Badge>
              )}
              <Badge
                variant="secondary"
                className="border-white/10 bg-white/10 text-paper-hero/80"
              >
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
            <Button
              variant="outline"
              size="sm"
              className="min-h-11 border-white/20 bg-white/10 text-paper-hero hover:bg-white/20 hover:text-paper-hero"
              asChild
            >
              <Link to="/t/$code/vocab" params={{ code }}>
                <BookA />
                {t(TERMS.vocabLearning)}
              </Link>
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="min-h-11 border-white/20 bg-white/10 text-paper-hero hover:bg-white/20 hover:text-paper-hero"
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
          <TabsList className="grid h-auto min-h-12 w-full grid-cols-3 gap-1 rounded-2xl border border-border/80 bg-card p-1.5 sm:w-fit">
            <TabsTrigger
              value="prepare"
              className="min-h-11 whitespace-normal px-2 py-2 text-center text-xs leading-5 data-[state=active]:bg-secondary data-[state=active]:shadow-none sm:px-6 sm:text-sm"
            >
              <ClipboardList
                aria-hidden="true"
                className="hidden size-4 sm:block"
              />
              {t({ zh: "练习安排", en: "Assign Practice" })}
            </TabsTrigger>
            <TabsTrigger
              value="results"
              className="min-h-11 whitespace-normal px-2 py-2 text-center text-xs leading-5 data-[state=active]:bg-secondary data-[state=active]:shadow-none sm:px-6 sm:text-sm"
            >
              <Users aria-hidden="true" className="hidden size-4 sm:block" />
              {t({ zh: "学生结果", en: "Student Results" })}
            </TabsTrigger>
            <TabsTrigger
              ref={historyTabRef}
              value="history"
              className="min-h-11 whitespace-normal px-2 py-2 text-center text-xs leading-5 data-[state=active]:bg-secondary data-[state=active]:shadow-none sm:px-6 sm:text-sm"
            >
              <History aria-hidden="true" className="hidden size-4 sm:block" />
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
            <ClassroomIssues
              code={code}
              onStudent={(id) => {
                setStatusFilter("all")
                setNameQuery("")
                setExpandedId(id)
              }}
            />
            {board.current_exercise && (
              <div className="flex flex-col gap-4 rounded-2xl border border-border/80 bg-card p-5 text-sm lg:flex-row lg:items-center">
                <div className="min-w-0 flex-1 space-y-2">
                  <p className="font-semibold">
                    {t({
                      zh: `今日 · v${board.current_exercise.version_no} · ${board.current_exercise.title}`,
                      en: `Today · v${board.current_exercise.version_no} · ${board.current_exercise.title}`,
                    })}
                  </p>
                  <p className="text-muted-foreground">
                    {t({
                      zh: "当前发布的作答记录；其他版本的成绩保存在发布历史中。",
                      en: "Answers for the current publication. Earlier results are saved in Publish History.",
                    })}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="min-h-11 shrink-0 self-start lg:self-center"
                  onClick={() => viewHistory(null)}
                >
                  {t({ zh: "查看历史版本结果", en: "View earlier results" })}
                </Button>
              </div>
            )}
            <BoardStatsCards
              studentsCount={board.students.length}
              classSize={board.class_size}
              submittedCount={board.submitted_count}
              classAvg={classAvg}
              inactiveCount={inactiveCount}
            />
            <BoardRosterCard
              code={code}
              hasStudents={hasStudents}
              filteredStudents={filteredStudents}
              totalStudents={board.students.length}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              nameQuery={nameQuery}
              onNameQueryChange={setNameQuery}
              onClearFilters={clearFilters}
              isExamPublish={board.current_exercise?.is_exam === true}
              expandedId={expandedId}
              onToggleRow={toggleRow}
              onShareLink={() => void shareLink()}
              onExportCsv={exportCsv}
            />

            <BoardTeachingActions
              attentionCount={attentionStudents.length}
              onCopyReminder={copyReminder}
              onAssignNext={() => setActiveTab("prepare")}
            />

            <Card className="border-accent/80 bg-accent/50 py-1 shadow-none">
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
              onCopied={() => setActiveTab("prepare")}
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
