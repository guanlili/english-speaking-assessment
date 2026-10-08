import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import { BookA, ListChecks, Mic, SpellCheck } from "lucide-react"
import { useState } from "react"
import { ApiError, ClassesService, VocabularyService } from "@/client"
import { AssignPanel } from "@/components/Teaching/VocabTasks/AssignPanel"
import { ResultsPanel } from "@/components/Teaching/VocabTasks/ResultsPanel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { APP_NAME } from "@/config"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"

export const Route = createFileRoute("/t/$code/vocab")({
  component: TeacherVocabPage,
  head: () => ({
    meta: [{ title: `词汇任务 / Vocabulary Tasks - ${APP_NAME}` }],
  }),
})

function TeacherVocabPage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/t/$code/vocab" })
  const [tab, setTab] = useState<"assign" | "results">("assign")
  // 查看哪一期：null = 当前进行中（后端默认最新发布）；任务列表点击后切换
  const [selectedAssignmentId, setSelectedAssignmentId] = useState<
    string | null
  >(null)

  const assignmentsQuery = useQuery({
    queryKey: ["vocab-teacher", code, "assignments"],
    queryFn: () =>
      VocabularyService.listAssignments({ code: code.toUpperCase() }),
  })
  const resultsQuery = useQuery({
    queryKey: ["vocab-teacher", code, "results"],
    queryFn: () =>
      VocabularyService.readVocabResults({ code: code.toUpperCase() }),
  })
  const classroomsQuery = useQuery({
    queryKey: ["teacher", "classrooms"],
    queryFn: () => ClassesService.listMyClassrooms(),
  })

  if (assignmentsQuery.isPending || resultsQuery.isPending) {
    return (
      <div role="status" className="space-y-6">
        <span className="sr-only">
          {t({ zh: "正在加载词汇任务…", en: "Loading vocabulary tasks…" })}
        </span>
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-11 w-64 rounded-xl" />
        <Skeleton className="h-80 rounded-2xl" />
      </div>
    )
  }

  const permissionDenied =
    (assignmentsQuery.error instanceof ApiError &&
      assignmentsQuery.error.status === 403) ||
    (resultsQuery.error instanceof ApiError &&
      resultsQuery.error.status === 403)

  if (permissionDenied) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-muted-foreground">
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

  const assignments = assignmentsQuery.data ?? []
  const current =
    assignments.find((item) => item.assignment.status === "published") ?? null
  // 建班级词库需要课堂 id：从我的课堂列表按码匹配（管理员也从这里拿）
  const classroomId =
    classroomsQuery.data?.find(
      (classroom) => classroom.code === code.toUpperCase(),
    )?.id ?? null
  const activeTasks = assignments.filter(
    (item) => item.assignment.status === "published",
  )
  const endedTasks = assignments.filter(
    (item) => item.assignment.status !== "published",
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/classrooms" className="text-sm font-medium text-primary">
          ← {t({ zh: "我的课堂", en: "My Classrooms" })}
        </Link>
        {/* 课堂内「口语 / 词汇」切换 */}
        <div className="flex gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link to="/t/$code" params={{ code }}>
              <Mic />
              {t({ zh: "口语练习", en: "Speaking" })}
            </Link>
          </Button>
          <Button size="sm" aria-current="page">
            <BookA />
            {t(TERMS.vocabLearning)}
          </Button>
        </div>
      </div>

      {/* 当前任务概览 */}
      <div className="rounded-2xl border border-primary/10 bg-secondary/40 p-5 sm:p-6">
        <p className="mb-1 text-[10px] font-semibold tracking-[0.18em] text-primary">
          VOCABULARY TASK
        </p>
        {current ? (
          <>
            <h1 className="break-words text-xl font-semibold tracking-tight sm:text-2xl">
              {current.assignment.title}
              <Badge variant="secondary" className="ml-2 align-middle">
                {t({
                  zh: `第 ${current.assignment.version_no} 期 · ${current.assignment.word_count} 词`,
                  en: `#${current.assignment.version_no} · ${current.assignment.word_count} words`,
                })}
              </Badge>
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t({
                zh: `发布于 ${current.assignment.published_at ? new Date(current.assignment.published_at).toLocaleString() : "–"}`,
                en: `Published ${current.assignment.published_at ? new Date(current.assignment.published_at).toLocaleString() : "–"}`,
              })}
              {current.assignment.due_at &&
                ` · ${t({ zh: "截止", en: "Due" })} ${new Date(current.assignment.due_at).toLocaleString()}`}
              {` · ${t({
                zh: `已完成 ${current.completed_count ?? 0}/${current.target_count ?? 0}`,
                en: `${current.completed_count ?? 0}/${current.target_count ?? 0} completed`,
              })}`}
              {(current.overdue_count ?? 0) > 0 &&
                ` · ${t({
                  zh: `${current.overdue_count ?? 0} 人逾期未完成`,
                  en: `${current.overdue_count ?? 0} overdue`,
                })}`}
            </p>
          </>
        ) : (
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            {t({
              zh: "还没有进行中的词汇任务",
              en: "No vocabulary task in progress",
            })}
          </h1>
        )}
      </div>

      {/* 任务列表（多任务并存：进行中 + 已结束分组；点击查看该任务结果） */}
      {assignments.length > 0 && (
        <section
          aria-label={t({ zh: "全部词汇任务", en: "All vocabulary tasks" })}
        >
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            {t({
              zh: "全部任务（新发布不再结束旧任务；点任务查看首轮成绩与复习轮）",
              en: "All tasks (publishing no longer ends older ones; tap a task for first-round scores and review rounds)",
            })}
          </p>
          <ul className="grid gap-2 lg:grid-cols-2">
            {[...activeTasks, ...endedTasks].map((row) => (
              <li key={row.assignment.id}>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedAssignmentId(row.assignment.id)
                    setTab("results")
                  }}
                  aria-current={
                    selectedAssignmentId === row.assignment.id
                      ? "true"
                      : undefined
                  }
                  className={`flex w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border px-4 py-3 text-left transition-colors hover:border-primary/40 ${
                    selectedAssignmentId === row.assignment.id
                      ? "border-primary/60 bg-primary/5"
                      : "border-border bg-card"
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">
                    {row.assignment.title}
                  </span>
                  <Badge
                    variant={
                      row.assignment.status === "published"
                        ? "secondary"
                        : "outline"
                    }
                  >
                    {row.assignment.status === "published"
                      ? t({ zh: "进行中", en: "Active" })
                      : t({ zh: "已结束", en: "Ended" })}
                  </Badge>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {t({
                      zh: `${row.completed_count ?? 0}/${row.target_count ?? 0} 完成`,
                      en: `${row.completed_count ?? 0}/${row.target_count ?? 0} done`,
                    })}
                    {(row.in_progress_count ?? 0) > 0 &&
                      ` · ${t({
                        zh: `${row.in_progress_count ?? 0} 进行中`,
                        en: `${row.in_progress_count ?? 0} active`,
                      })}`}
                    {(row.overdue_count ?? 0) > 0 &&
                      ` · ${t({
                        zh: `${row.overdue_count ?? 0} 逾期`,
                        en: `${row.overdue_count ?? 0} overdue`,
                      })}`}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div
        className="flex gap-2"
        role="tablist"
        aria-label={t({ zh: "词汇任务视图", en: "Vocabulary task views" })}
      >
        <Button
          variant={tab === "assign" ? "default" : "outline"}
          size="sm"
          aria-pressed={tab === "assign"}
          onClick={() => setTab("assign")}
        >
          <ListChecks />
          {t({ zh: "发布任务", en: "Assign" })}
        </Button>
        <Button
          variant={tab === "results" ? "default" : "outline"}
          size="sm"
          aria-pressed={tab === "results"}
          onClick={() => setTab("results")}
        >
          <SpellCheck />
          {t({ zh: "完成情况", en: "Results" })}
        </Button>
      </div>

      {tab === "assign" ? (
        <AssignPanel code={code} classroomId={classroomId} />
      ) : (
        <ResultsPanel
          code={code}
          assignments={assignments.map((row) => row.assignment)}
          selectedAssignmentId={selectedAssignmentId}
          onSelectAssignment={setSelectedAssignmentId}
        />
      )}
    </div>
  )
}
