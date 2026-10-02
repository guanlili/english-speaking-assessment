import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import {
  Archive,
  BookA,
  CheckCircle2,
  CircleDashed,
  Download,
  ListChecks,
  Loader2,
  Mic,
  Plus,
  RefreshCw,
  SpellCheck,
  Upload,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { ApiError, ClassesService, VocabularyService } from "@/client"
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
import { APP_NAME } from "@/config"
import { downloadCsv } from "@/lib/csv"
import { type BiString, useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"
import { localizeImportIssue } from "@/lib/vocabImport"

export const Route = createFileRoute("/t/$code/vocab")({
  component: TeacherVocabPage,
  head: () => ({
    meta: [{ title: `词汇任务 / Vocabulary Tasks - ${APP_NAME}` }],
  }),
})

const MAX_PUBLISH_WORDS = 100

/** 学生完成状态 → 双语标签 */
const STUDENT_STATUS: Record<string, BiString> = {
  completed: { zh: "已完成", en: "Completed" },
  in_progress: { zh: "进行中", en: "In progress" },
  not_started: { zh: "未开始", en: "Not started" },
}

function TeacherVocabPage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/t/$code/vocab" })
  const [tab, setTab] = useState<"assign" | "results">("assign")

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
    assignments.find((item) => item.status === "published") ?? null
  // 建班级词库需要课堂 id：从我的课堂列表按码匹配（管理员也从这里拿）
  const classroomId =
    classroomsQuery.data?.find(
      (classroom) => classroom.code === code.toUpperCase(),
    )?.id ?? null

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
              {current.title}
              <Badge variant="secondary" className="ml-2 align-middle">
                {t({
                  zh: `第 ${current.version_no} 期 · ${current.word_count} 词`,
                  en: `#${current.version_no} · ${current.word_count} words`,
                })}
              </Badge>
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t({
                zh: `发布于 ${current.published_at ? new Date(current.published_at).toLocaleString() : "–"}`,
                en: `Published ${current.published_at ? new Date(current.published_at).toLocaleString() : "–"}`,
              })}
              {current.due_at &&
                ` · ${t({ zh: "截止", en: "Due" })} ${new Date(current.due_at).toLocaleString()}`}
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
        <ResultsPanel code={code} assignments={assignments} />
      )}
    </div>
  )
}

/** 发布面板：选词库（可现场新建班级词库）→ 勾词 → 预览题量 → 发布快照 */
function AssignPanel({
  code,
  classroomId,
}: {
  code: string
  classroomId: string | null
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const booksQuery = useQuery({
    queryKey: ["vocab-teacher", "books"],
    queryFn: () => VocabularyService.listBooks(),
  })
  const books = (booksQuery.data ?? []).filter(
    (book) => book.status === "active",
  )

  const [bookId, setBookId] = useState<string | null>(null)
  const detailQuery = useQuery({
    queryKey: ["vocab-teacher", "book", bookId],
    queryFn: () => VocabularyService.readBook({ bookId: bookId as string }),
    enabled: bookId !== null,
  })
  const words = detailQuery.data?.words ?? []

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [title, setTitle] = useState("")
  const [meaningPrompt, setMeaningPrompt] = useState(true)
  const [audioPrompt, setAudioPrompt] = useState(false)
  const [dueLocal, setDueLocal] = useState("")
  const [showCreateBook, setShowCreateBook] = useState(false)

  const selectBook = (id: string | null) => {
    setBookId(id)
    setSelected(new Set())
    setTitle("")
  }
  const toggleAll = (checked: boolean) => {
    setSelected(
      checked
        ? new Set(words.filter((w) => w.status === "active").map((w) => w.id))
        : new Set(),
    )
  }
  const toggleWord = (id: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const publish = useMutation({
    mutationFn: () =>
      VocabularyService.publishVocabAssignment({
        code: code.toUpperCase(),
        requestBody: {
          title: title.trim() || null,
          word_ids: Array.from(selected),
          prompt_types: [
            ...(meaningPrompt ? ["meaning"] : []),
            ...(audioPrompt ? ["audio"] : []),
          ],
          due_at: dueLocal ? new Date(dueLocal).toISOString() : null,
        },
      }),
    onSuccess: () => {
      toast.success(
        t({
          zh: "词汇任务已发布，快照已固化。",
          en: "Vocabulary task published with a fixed snapshot.",
        }),
      )
      queryClient.invalidateQueries({ queryKey: ["vocab-teacher", code] })
      setDueLocal("")
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(
          error.status === 422
            ? t({
                zh: "发布内容有误：请检查所选词数与出题方式（纯听音要求全部词有标准音）。",
                en: "Cannot publish: check the words and prompt types (audio-only requires standard audio for every word).",
              })
            : error.status === 403
              ? t({
                  zh: "没有权限使用这些词条，请从自己的词库重新选择。",
                  en: "No permission to use some of these words — pick from your own books.",
                })
              : t({
                  zh: "发布失败，请重试。",
                  en: "Publish failed — please retry.",
                }),
        )
      }
    },
  })

  const selectedCount = selected.size
  const activeCount = words.filter((w) => w.status === "active").length

  const canPublish =
    selectedCount > 0 &&
    selectedCount <= MAX_PUBLISH_WORDS &&
    (meaningPrompt || audioPrompt) &&
    !publish.isPending

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "发布词汇任务", en: "Publish a vocabulary task" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "从词库选词发布。发布后内容固化为快照：之后再改词库，不影响这个任务和已完成的成绩。",
              en: "Pick words from a book and publish. The content is fixed as a snapshot: later book edits never change this task or its results.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* 1. 选词库 */}
          <div className="space-y-2">
            <label htmlFor="vocab-book" className="text-sm font-medium">
              1. {t({ zh: "选择词库", en: "Choose a word book" })}
            </label>
            <select
              id="vocab-book"
              value={bookId ?? ""}
              onChange={(event) => selectBook(event.target.value || null)}
              className="h-11 w-full max-w-md rounded-xl border border-input bg-card px-3 text-base text-foreground transition-colors hover:border-primary/35"
            >
              <option value="">
                {t({ zh: "请选择词库…", en: "Select a word book…" })}
              </option>
              {books.map((book) => (
                <option key={book.id} value={book.id}>
                  {book.title}（{book.word_count} {t({ zh: "词", en: "words" })}
                  ·
                  {book.scope === "public"
                    ? t({ zh: "公共", en: "public" })
                    : t({ zh: "班级", en: "class" })}
                  ）
                </option>
              ))}
            </select>
            {books.length === 0 && !booksQuery.isPending && (
              <p className="text-xs text-muted-foreground">
                {t({
                  zh: "还没有可用词库：可以用下面的「新建班级词库」导入一份，公共词库由管理员维护。",
                  en: "No books yet: create a classroom book below, or ask an admin for public books.",
                })}
              </p>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="text-xs text-primary"
              aria-expanded={showCreateBook}
              onClick={() => setShowCreateBook(!showCreateBook)}
            >
              <Plus />
              {t({ zh: "新建班级词库", en: "New classroom book" })}
            </Button>
            {showCreateBook && (
              <CreateClassroomBook
                classroomId={classroomId}
                onCreated={(newBookId) => {
                  setShowCreateBook(false)
                  queryClient.invalidateQueries({
                    queryKey: ["vocab-teacher", "books"],
                  })
                  selectBook(newBookId)
                }}
              />
            )}
          </div>

          {/* 2. 勾词 */}
          {bookId && detailQuery.isPending && (
            <div
              role="status"
              className="flex items-center gap-2 text-sm text-muted-foreground"
            >
              <Loader2 className="size-4 animate-spin" />
              {t({ zh: "正在加载词条…", en: "Loading words…" })}
            </div>
          )}
          {bookId && !detailQuery.isPending && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium">
                  2.{" "}
                  {t({
                    zh: `勾选要考的词（已选 ${selectedCount}/${activeCount}）`,
                    en: `Pick words to test (${selectedCount}/${activeCount} selected)`,
                  })}
                </p>
                <div className="flex flex-wrap gap-2">
                  {detailQuery.data?.scope === "classroom" ? (
                    // key=bookId：切换词库即重挂载，清掉未确认的 CSV 预览，
                    // 防止 A 库的预览词条被确认进 B 库（飞行中的预览请求
                    // 回来后 setState 到已卸载组件是 no-op，同样安全）
                    <AddWordsToBook
                      key={bookId}
                      bookId={bookId}
                      onAdded={() => {
                        queryClient.invalidateQueries({
                          queryKey: ["vocab-teacher", "book", bookId],
                        })
                      }}
                    />
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      {t({
                        zh: "公共词库由管理员在「词库管理」维护；要自己加词可新建班级词库。",
                        en: "Public books are maintained by admins; create a classroom book to add your own words.",
                      })}
                    </p>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => toggleAll(true)}
                  >
                    {t({ zh: "全选", en: "Select all" })}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => toggleAll(false)}
                  >
                    {t({ zh: "清空", en: "Clear" })}
                  </Button>
                </div>
              </div>
              {activeCount === 0 && (
                <p role="status" className="text-sm text-muted-foreground">
                  {t({
                    zh: "这个词库还没有词：点上面的「CSV 加词」导入，或回到第一步新建词库。",
                    en: "This book is empty — import via “Add words via CSV” above, or go back and create a book.",
                  })}
                </p>
              )}
              {selectedCount > MAX_PUBLISH_WORDS && (
                <p role="alert" className="text-sm text-destructive">
                  {t({
                    zh: `一次最多发布 ${MAX_PUBLISH_WORDS} 个词，请减少选择。`,
                    en: `A task can have at most ${MAX_PUBLISH_WORDS} words — select fewer.`,
                  })}
                </p>
              )}
              <div className="grid max-h-80 gap-1.5 overflow-y-auto rounded-xl border p-3 sm:grid-cols-2">
                {words.map((word) => (
                  <label
                    key={word.id}
                    className={`flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors ${
                      selected.has(word.id)
                        ? "bg-secondary text-foreground"
                        : "text-muted-foreground hover:bg-secondary/50"
                    } ${word.status === "archived" ? "pointer-events-none opacity-50" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(word.id)}
                      onChange={(event) =>
                        toggleWord(word.id, event.target.checked)
                      }
                      className="size-4 accent-[var(--primary)]"
                    />
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-semibold">{word.headword}</span>
                      {word.part_of_speech && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          {word.part_of_speech}
                        </span>
                      )}
                      <span className="ml-2 text-muted-foreground">
                        {word.meaning_zh}
                      </span>
                    </span>
                    {word.status === "archived" && (
                      <Badge variant="outline">
                        {t({ zh: "已归档", en: "Archived" })}
                      </Badge>
                    )}
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* 3. 任务设置 */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <label htmlFor="vocab-title" className="text-sm font-medium">
                3. {t({ zh: "任务名称", en: "Task title" })}
              </label>
              <Input
                id="vocab-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={t({
                  zh: "词汇练习（默认）",
                  en: "Vocabulary practice (default)",
                })}
                className="h-11 max-w-md text-base"
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="vocab-due" className="text-sm font-medium">
                {t({ zh: "截止时间（可选）", en: "Due time (optional)" })}
              </label>
              <Input
                id="vocab-due"
                type="datetime-local"
                value={dueLocal}
                onChange={(event) => setDueLocal(event.target.value)}
                className="h-11 max-w-md text-base"
              />
            </div>
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium">
              4. {t({ zh: "出题方式", en: "Prompt types" })}
            </p>
            <div className="flex flex-wrap gap-4">
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={meaningPrompt}
                  onChange={(event) => setMeaningPrompt(event.target.checked)}
                  className="size-4 accent-[var(--primary)]"
                />
                {t(TERMS.promptMeaning)}
              </label>
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={audioPrompt}
                  onChange={(event) => setAudioPrompt(event.target.checked)}
                  className="size-4 accent-[var(--primary)]"
                />
                {t(TERMS.promptAudio)}
                <span className="text-xs text-muted-foreground">
                  {t({
                    zh: "（无标准音的词自动走看义；纯听音任务要求全部词有标准音）",
                    en: "(words without audio fall back to meaning; audio-only tasks need audio for every word)",
                  })}
                </span>
              </label>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t pt-4">
            <Button
              size="lg"
              disabled={!canPublish}
              onClick={() => publish.mutate()}
            >
              {publish.isPending ? (
                <Loader2 className="animate-spin" />
              ) : (
                <CheckCircle2 />
              )}
              {t({
                zh: `发布（${selectedCount} 词）`,
                en: `Publish (${selectedCount} words)`,
              })}
            </Button>
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "发布前请核对：所选词数 = 实际出题数。任务开始后不能再改内容，改词请发布新一期。",
                en: "Before publishing, check that selected words = actual items. Content is fixed once published; to change words, publish a new round.",
              })}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

/** 结果面板：完成统计 + 学生明细 + 逐词错误分布 */
/** 期数选择器：当前任务 / 历史期数（含已归档）；无历史时不渲染。 */
function RoundSelector({
  assignments,
  selectedAssignmentId,
  onSelect,
  className,
}: {
  assignments: Array<{
    id: string
    version_no: number
    title: string
    status: string
    word_count: number
  }>
  selectedAssignmentId: string | null
  onSelect: (id: string | null) => void
  className?: string
}) {
  const { t } = useI18n()
  if (assignments.length === 0) return null
  return (
    <div className={`flex flex-wrap items-center gap-2 ${className ?? ""}`}>
      <label
        htmlFor="vocab-round"
        className="text-xs font-medium text-muted-foreground"
      >
        {t({ zh: "查看期数：", en: "Round:" })}
      </label>
      <select
        id="vocab-round"
        value={selectedAssignmentId ?? ""}
        onChange={(event) => onSelect(event.target.value || null)}
        className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground transition-colors hover:border-primary/35"
      >
        <option value="">
          {t({ zh: "当前进行中的任务", en: "Current task in progress" })}
        </option>
        {assignments.map((item) => (
          <option key={item.id} value={item.id}>
            {`#${item.version_no} ${item.title}（${item.word_count} ${t({ zh: "词", en: "words" })} · ${
              item.status === "published"
                ? t({ zh: "进行中", en: "active" })
                : t({ zh: "已归档", en: "archived" })
            }）`}
          </option>
        ))}
      </select>
    </div>
  )
}

function ResultsPanel({
  code,
  assignments,
}: {
  code: string
  assignments: Array<{
    id: string
    version_no: number
    title: string
    status: string
    word_count: number
  }>
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  // 查看哪一期：null = 当前进行中；归档/重发后可切换历史期数按快照回看
  const [selectedAssignmentId, setSelectedAssignmentId] = useState<
    string | null
  >(null)
  const resultsQuery = useQuery({
    queryKey: ["vocab-teacher", code, "results", selectedAssignmentId],
    queryFn: () =>
      VocabularyService.readVocabResults({
        code: code.toUpperCase(),
        assignmentId: selectedAssignmentId ?? undefined,
      }),
    refetchInterval: 20_000,
  })
  const archive = useMutation({
    mutationFn: (assignmentId: string) =>
      VocabularyService.archiveVocabAssignment({
        code: code.toUpperCase(),
        assignmentId,
      }),
    onSuccess: () => {
      toast.success(t({ zh: "任务已结束。", en: "Task archived." }))
      queryClient.invalidateQueries({ queryKey: ["vocab-teacher", code] })
    },
  })

  const results = resultsQuery.data
  const assignment = results?.assignment ?? null
  // 没有当前任务但有历史期数（如刚结束最后一期）→ 默认选中最近一期，
  // 保证归档成绩始终能从选择器进入（hook 必须在条件 return 之前）
  useEffect(() => {
    if (
      !assignment &&
      selectedAssignmentId === null &&
      assignments.length > 0
    ) {
      setSelectedAssignmentId(assignments[0].id)
    }
  }, [assignment, selectedAssignmentId, assignments])
  const students = useMemo(
    () =>
      [...(results?.students ?? [])].sort((a, b) =>
        a.display_name.localeCompare(b.display_name, "zh-Hans-CN"),
      ),
    [results],
  )
  const words = results?.words ?? []

  const exportCsv = () => {
    if (!results) return
    const header = [
      t({ zh: "姓名", en: "Name" }),
      t({ zh: "区分码", en: "Suffix" }),
      t({ zh: "状态", en: "Status" }),
      t({ zh: "已答/总词数", en: "Answered/Total" }),
      t({ zh: "首答正确", en: "First-try correct" }),
      t({ zh: "首答正确率", en: "First-try accuracy" }),
    ]
    const rows = students.map((row) => [
      row.display_name,
      row.suffix ?? "",
      t(STUDENT_STATUS[row.status] ?? { zh: row.status, en: row.status }),
      `${row.answered_count}/${row.total_count}`,
      String(row.correct_first_count),
      row.answered_count > 0
        ? `${Math.round((row.correct_first_count / row.answered_count) * 100)}%`
        : "-",
    ])
    downloadCsv(
      [header, ...rows],
      t({
        zh: `课堂${code}-词汇任务-${new Date().toISOString().slice(0, 10)}.csv`,
        en: `classroom-${code}-vocabulary-${new Date().toISOString().slice(0, 10)}.csv`,
      }),
    )
  }

  if (resultsQuery.isPending) {
    return (
      <div role="status" className="space-y-4">
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    )
  }

  if (!assignment) {
    return (
      <div className="space-y-6">
        <RoundSelector
          assignments={assignments}
          selectedAssignmentId={selectedAssignmentId}
          onSelect={setSelectedAssignmentId}
        />
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            {selectedAssignmentId === null
              ? t({
                  zh: "还没有词汇任务，先到「发布任务」安排一期。",
                  en: "No vocabulary tasks yet — assign one first.",
                })
              : t({
                  zh: "该期数没有结果数据。",
                  en: "No result data for this round.",
                })}
          </CardContent>
        </Card>
      </div>
    )
  }

  const target = results?.target_count ?? 0
  const completed = results?.completed_count ?? 0
  const inProgress = results?.in_progress_count ?? 0
  const notStarted = results?.not_started_count ?? 0
  const errorWords = words.filter((w) => w.error_count > 0)

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "名单学生", en: "Roster" })}
            </p>
            <p className="mt-1 text-2xl font-bold">{target}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "已完成", en: "Completed" })}
            </p>
            <p className="mt-1 text-2xl font-bold text-primary">{completed}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "进行中", en: "In progress" })}
            </p>
            <p className="mt-1 text-2xl font-bold">{inProgress}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">
              {t({ zh: "未开始", en: "Not started" })}
            </p>
            <p className="mt-1 text-2xl font-bold text-muted-foreground">
              {notStarted}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card className="border-primary/20 bg-secondary/30">
        <CardContent className="flex flex-wrap items-center gap-3 py-4">
          <div className="mr-auto min-w-48">
            <p className="text-sm font-semibold">
              {t({
                zh: `完成率 ${target > 0 ? Math.round((completed / target) * 100) : 0}%`,
                en: `Completion ${target > 0 ? Math.round((completed / target) * 100) : 0}%`,
              })}
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {t({
                  zh: "（分母 = 发布时的名单，后加入的学生不计入）",
                  en: "(denominator = roster fixed at publish time)",
                })}
              </span>
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t({
                zh: "成绩按每题第一次作答统计；练习重试不冲高正确率。",
                en: "Stats use each item's first answer; practice retries don't inflate accuracy.",
              })}
            </p>
            <RoundSelector
              assignments={assignments}
              selectedAssignmentId={selectedAssignmentId}
              onSelect={setSelectedAssignmentId}
              className="mt-2"
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void resultsQuery.refetch()}
            disabled={resultsQuery.isFetching}
          >
            <RefreshCw
              className={resultsQuery.isFetching ? "animate-spin" : ""}
            />
            {t({ zh: "刷新", en: "Refresh" })}
          </Button>
          <Button variant="outline" size="sm" onClick={exportCsv}>
            <Download />
            {t({ zh: "导出", en: "Export" })}
          </Button>
          {assignment.status === "published" && (
            <Button
              variant="outline"
              size="sm"
              disabled={archive.isPending}
              onClick={() => archive.mutate(assignment.id)}
            >
              <Archive />
              {t({ zh: "结束任务", en: "End task" })}
            </Button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "逐词错误分布", en: "Per-word errors" })}
          </CardTitle>
          <CardDescription>
            {errorWords.length === 0
              ? t({
                  zh: "还没有错词——学生都还没开始，或首答全对。",
                  en: "No errors yet — either nobody started, or first tries are all correct.",
                })
              : t({
                  zh: "按首答统计；常见误拼取前 5，可据此安排课堂复习。",
                  en: "First answers only; top-5 misspellings shown to plan in-class review.",
                })}
            <span className="mt-1 block sm:hidden">
              {t({
                zh: "横向滑动表格，可以查看完整数据。",
                en: "Swipe the table sideways to see all data.",
              })}
            </span>
          </CardDescription>
        </CardHeader>
        <CardContent className="pb-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t({ zh: "单词", en: "Word" })}</TableHead>
                <TableHead>{t({ zh: "释义", en: "Meaning" })}</TableHead>
                <TableHead>
                  {t({ zh: "已答/名单", en: "Answered/Roster" })}
                </TableHead>
                <TableHead>
                  {t({ zh: "首答正确", en: "First-try correct" })}
                </TableHead>
                <TableHead>
                  {t({ zh: "常见误拼", en: "Common misspellings" })}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {words.map((word) => (
                <TableRow key={word.word_id}>
                  <TableCell className="font-semibold">
                    {word.headword}
                    <span className="ml-2 font-normal text-xs text-muted-foreground">
                      #{word.item_index + 1}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {word.meaning_zh}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {word.answered_count}/{target}
                  </TableCell>
                  <TableCell>
                    {word.error_count > 0 ? (
                      <span className="font-semibold tabular-nums">
                        {word.correct_first_count}
                        <span className="ml-1 text-xs font-normal text-muted-foreground">
                          ({t({ zh: "错", en: "miss" })} {word.error_count})
                        </span>
                      </span>
                    ) : (
                      <span className="tabular-nums">
                        {word.correct_first_count}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {(word.misspellings ?? []).length === 0
                      ? "–"
                      : (word.misspellings ?? []).map((miss) => (
                          <Badge
                            key={miss.answer}
                            variant="outline"
                            className="mr-1.5 font-mono"
                          >
                            {miss.answer}×{miss.count}
                          </Badge>
                        ))}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "学生完成情况", en: "Student completion" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "零作答显示「未开始」，不折算成 0% 正确率。",
              en: 'Zero answers show as "Not started", not 0% accuracy.',
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="pb-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t({ zh: "姓名", en: "Name" })}</TableHead>
                <TableHead>{t({ zh: "状态", en: "Status" })}</TableHead>
                <TableHead>{t({ zh: "已答", en: "Answered" })}</TableHead>
                <TableHead>
                  {t({ zh: "首答正确", en: "First-try correct" })}
                </TableHead>
                <TableHead>
                  {t({ zh: "首答正确率", en: "First-try accuracy" })}
                </TableHead>
                <TableHead>
                  {t({ zh: "交卷时间", en: "Submitted at" })}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {students.map((row) => {
                const name = row.suffix
                  ? `${row.display_name}·${row.suffix}`
                  : row.display_name
                return (
                  <TableRow key={row.student_id}>
                    <TableCell className="font-medium">{name}</TableCell>
                    <TableCell>
                      {row.status === "completed" ? (
                        <Badge variant="outline" className="text-primary">
                          <CheckCircle2 className="size-3" />
                          {t(STUDENT_STATUS.completed)}
                        </Badge>
                      ) : row.status === "in_progress" ? (
                        <Badge variant="secondary">
                          <CircleDashed className="size-3" />
                          {t(STUDENT_STATUS.in_progress)}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">
                          {t(STUDENT_STATUS.not_started)}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {row.answered_count}/{row.total_count}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {row.correct_first_count}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {row.answered_count > 0
                        ? `${Math.round((row.correct_first_count / row.answered_count) * 100)}%`
                        : "–"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {row.submitted_at
                        ? new Date(row.submitted_at).toLocaleTimeString()
                        : "–"}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <p className="pb-6 text-center text-xs text-muted-foreground">
        {t({
          zh: "统计只看每题第一次作答，帮助学生看见真实起点；练习数据辅助教学，不定义学生。",
          en: "Stats reflect each item's first answer, showing students' real starting points. Practice data supports teaching — it doesn't define students.",
        })}
      </p>
    </div>
  )
}

/** CSV 预览行（导入确认用；保留全部支持字段，避免 meaning_en/example_en 静默丢失） */

type BookWordInput = {
  headword: string
  part_of_speech?: string | null
  meaning_zh: string
  meaning_en?: string | null
  accepted_spellings?: Array<string> | null
  example_en?: string | null
}

/** 向已有班级词库补词：CSV 预览确认后调用 addBookWords（库里已有的自动跳过）。 */
function AddWordsToBook({
  bookId,
  onAdded,
}: {
  bookId: string
  onAdded: () => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  // 预览同时保留问题行（无效/文件内重复），确认前让教师看清会跳过哪些
  const [preview, setPreview] = useState<{
    words: BookWordInput[]
    invalid: Array<{ line: number; reason: string }>
    duplicates: Array<{ line: number; reason: string }>
  } | null>(null)

  const importPreview = useMutation({
    mutationFn: (file: File) =>
      VocabularyService.importVocabPreview({
        formData: { file: file as unknown as string },
      }),
    onSuccess: (data) => {
      setPreview({
        words: (data.rows ?? []).map((row) => ({
          headword: row.word.headword,
          part_of_speech: row.word.part_of_speech ?? null,
          meaning_zh: row.word.meaning_zh,
          meaning_en: row.word.meaning_en ?? null,
          accepted_spellings: row.word.accepted_spellings ?? null,
          example_en: row.word.example_en ?? null,
        })),
        invalid: data.invalid ?? [],
        duplicates: data.duplicates ?? [],
      })
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(
          error.status === 422
            ? t({
                zh: "CSV 格式有误：需要表头 headword,meaning_zh（UTF-8）。",
                en: "Bad CSV: header row headword,meaning_zh required (UTF-8).",
              })
            : t({
                zh: "解析失败，请重试。",
                en: "Preview failed — please retry.",
              }),
        )
      }
    },
  })

  const addWords = useMutation({
    mutationFn: () =>
      VocabularyService.addBookWords({
        bookId,
        requestBody: preview?.words ?? [],
      }),
    onSuccess: (data) => {
      const submitted = preview?.words.length ?? 0
      toast.success(
        t({
          zh: `已处理 ${submitted} 行（库里已有的自动跳过），词库现有 ${data.word_count ?? 0} 词。`,
          en: `Processed ${submitted} rows (existing words skipped); the book now has ${data.word_count ?? 0} words.`,
        }),
      )
      setPreview(null)
      queryClient.invalidateQueries({ queryKey: ["vocab-teacher", "books"] })
      onAdded()
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(
          error.status === 403
            ? t({
                zh: "没有权限编辑这个词库（公共词库请在管理端维护）。",
                en: "No permission to edit this book (public books are maintained by admins).",
              })
            : t({
                zh: "加词失败，请重试。",
                en: "Failed to add words — please retry.",
              }),
        )
      }
    },
  })

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => fileRef.current?.click()}
        disabled={importPreview.isPending}
      >
        {importPreview.isPending ? (
          <Loader2 className="animate-spin" />
        ) : (
          <Upload />
        )}
        {t({ zh: "CSV 加词", en: "Add words via CSV" })}
      </Button>
      <input
        ref={fileRef}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) importPreview.mutate(file)
          event.target.value = ""
        }}
      />
      {preview && (
        <div className="flex w-full flex-col gap-1.5 rounded-lg bg-secondary/60 px-3 py-2">
          <span className="text-xs text-muted-foreground">
            {t({
              zh: `预览 ${preview.words.length} 词：`,
              en: `Preview ${preview.words.length} words:`,
            })}
            {preview.words
              .slice(0, 6)
              .map((word) => word.headword)
              .join("、")}
            {preview.words.length > 6 &&
              t({
                zh: ` 等 ${preview.words.length} 词`,
                en: ` …${preview.words.length} in total`,
              })}
            {preview.invalid.length > 0 &&
              t({
                zh: `；无效 ${preview.invalid.length} 行将跳过`,
                en: `; ${preview.invalid.length} invalid rows will be skipped`,
              })}
            {preview.duplicates.length > 0 &&
              t({
                zh: `；文件内重复 ${preview.duplicates.length} 行将跳过`,
                en: `; ${preview.duplicates.length} duplicate rows will be skipped`,
              })}
          </span>
          {(preview.invalid.length > 0 || preview.duplicates.length > 0) && (
            <ul className="text-xs text-muted-foreground">
              {[...preview.invalid, ...preview.duplicates]
                .slice(0, 4)
                .map((issue) => (
                  <li key={`${issue.line}-${issue.reason}`}>
                    {t({ zh: "第", en: "Line" })} {issue.line}{" "}
                    {t({ zh: "行", en: "" })}：
                    {t(localizeImportIssue(issue.reason))}
                  </li>
                ))}
            </ul>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={addWords.isPending || preview.words.length === 0}
              onClick={() => addWords.mutate()}
            >
              {addWords.isPending ? <Loader2 className="animate-spin" /> : null}
              {t({ zh: "确认加入", en: "Confirm" })}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setPreview(null)}>
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

/** 新建班级词库：标题 + 可选 CSV 预览导入，绑定当前课堂（scope=classroom）。 */
function CreateClassroomBook({
  classroomId,
  onCreated,
}: {
  classroomId: string | null
  onCreated: (bookId: string) => void
}) {
  const { t } = useI18n()
  const fileRef = useRef<HTMLInputElement>(null)
  const [title, setTitle] = useState("")
  const [preview, setPreview] = useState<{
    words: BookWordInput[]
    invalid: Array<{ line: number; reason: string }>
    duplicates: Array<{ line: number; reason: string }>
  } | null>(null)

  const importPreview = useMutation({
    mutationFn: (file: File) =>
      VocabularyService.importVocabPreview({
        formData: { file: file as unknown as string },
      }),
    onSuccess: (data) => {
      setPreview({
        words: (data.rows ?? []).map((row) => ({
          headword: row.word.headword,
          part_of_speech: row.word.part_of_speech ?? null,
          meaning_zh: row.word.meaning_zh,
          meaning_en: row.word.meaning_en ?? null,
          accepted_spellings: row.word.accepted_spellings ?? null,
          example_en: row.word.example_en ?? null,
        })),
        invalid: data.invalid ?? [],
        duplicates: data.duplicates ?? [],
      })
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(
          error.status === 422
            ? t({
                zh: "CSV 格式有误：需要表头 headword,meaning_zh（UTF-8）。",
                en: "Bad CSV: header row headword,meaning_zh required (UTF-8).",
              })
            : t({
                zh: "解析失败，请重试。",
                en: "Preview failed — please retry.",
              }),
        )
      }
    },
  })

  const create = useMutation({
    mutationFn: () =>
      VocabularyService.createBook({
        requestBody: {
          title: title.trim() || t({ zh: "班级词库", en: "Classroom book" }),
          scope: "classroom",
          classroom_id: classroomId,
          description: null,
          words: preview?.words ?? [],
        },
      }),
    onSuccess: (book) => {
      toast.success(
        t({
          zh: `班级词库已创建（${book.word_count ?? 0} 词）。`,
          en: `Classroom book created (${book.word_count ?? 0} words).`,
        }),
      )
      onCreated(book.id)
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(
          error.status === 403
            ? t({
                zh: "只有本班任课教师能创建班级词库。",
                en: "Only this classroom's teacher can create its books.",
              })
            : t({
                zh: "创建失败，请重试。",
                en: "Create failed — please retry.",
              }),
        )
      }
    },
  })

  if (classroomId === null) {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        {t({
          zh: "课堂信息加载中，稍后即可新建…",
          en: "Loading classroom info — creation will be available shortly…",
        })}
      </p>
    )
  }

  return (
    <div className="space-y-3 rounded-xl border border-dashed border-primary/40 bg-secondary/40 p-4">
      <div className="space-y-2">
        <label htmlFor="class-book-title" className="text-sm font-medium">
          {t({ zh: "词库名称", en: "Book title" })}
        </label>
        <Input
          id="class-book-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder={t({
            zh: "如：Unit 1-2 单词（本班专属）",
            en: "e.g. Units 1-2 words (class only)",
          })}
          className="h-11 max-w-md text-base"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => fileRef.current?.click()}
          disabled={importPreview.isPending}
        >
          {importPreview.isPending ? (
            <Loader2 className="animate-spin" />
          ) : (
            <Upload />
          )}
          {t({ zh: "选择 CSV 预览", en: "Choose CSV to preview" })}
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) importPreview.mutate(file)
            event.target.value = ""
          }}
        />
        <Button
          size="sm"
          disabled={
            create.isPending || (preview !== null && title.trim() === "")
          }
          onClick={() => create.mutate()}
        >
          {create.isPending ? <Loader2 className="animate-spin" /> : null}
          {preview && preview.words.length > 0
            ? t({
                zh: `创建（含 ${preview.words.length} 词）`,
                en: `Create (${preview.words.length} words)`,
              })
            : t({ zh: "创建空词库", en: "Create empty book" })}
        </Button>
        <span className="text-xs text-muted-foreground">
          {t({
            zh: "CSV 表头：headword,meaning_zh（可选 part_of_speech/meaning_en/accepted_spellings/example_en）",
            en: "CSV header: headword,meaning_zh (optional part_of_speech/meaning_en/accepted_spellings/example_en)",
          })}
        </span>
      </div>
      {preview && (
        <div>
          <p className="text-sm">
            {t({ zh: "预览：有效 ", en: "Preview: " })}
            <strong>{preview.words.length}</strong>
            {t({ zh: " 行", en: " valid rows" })}
            {preview.invalid.length > 0 &&
              t({
                zh: `，无效 ${preview.invalid.length} 行`,
                en: `, ${preview.invalid.length} invalid`,
              })}
            {preview.duplicates.length > 0 &&
              t({
                zh: `，文件内重复 ${preview.duplicates.length} 行（将跳过）`,
                en: `, ${preview.duplicates.length} duplicates (skipped)`,
              })}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {preview.words.slice(0, 10).map((word) => (
              <span
                key={`${word.headword}-${word.meaning_zh}`}
                className="rounded bg-secondary px-2 py-0.5 text-xs text-primary"
              >
                {word.headword} · {word.meaning_zh}
              </span>
            ))}
            {preview.words.length > 10 && (
              <span className="text-xs text-muted-foreground">
                {t({
                  zh: `…共 ${preview.words.length} 个`,
                  en: `…${preview.words.length} in total`,
                })}
              </span>
            )}
          </div>
          {(preview.invalid.length > 0 || preview.duplicates.length > 0) && (
            <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
              {[...preview.invalid, ...preview.duplicates]
                .slice(0, 4)
                .map((issue) => (
                  <li key={`${issue.line}-${issue.reason}`}>
                    {t({ zh: "第", en: "Line" })} {issue.line}{" "}
                    {t({ zh: "行", en: "" })}：
                    {t(localizeImportIssue(issue.reason))}
                  </li>
                ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
