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
  RefreshCw,
  SpellCheck,
} from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import { ApiError, VocabularyService } from "@/client"
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
        <AssignPanel code={code} currentDue={current?.due_at ?? null} />
      ) : (
        <ResultsPanel code={code} />
      )}
    </div>
  )
}

/** 发布面板：选词库 → 勾词 → 预览题量 → 发布快照 */
function AssignPanel({
  code,
  currentDue,
}: {
  code: string
  currentDue: string | null
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
      setDueLocal(currentDue ?? "")
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(
          error.status === 422
            ? t({
                zh: "发布内容有误：请检查所选词数与出题方式。",
                en: "Cannot publish: check the selected words and prompt types.",
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
                  zh: "还没有可用词库：公共词库由管理员在「词库管理」维护，也可以在题目库创建班级词库。",
                  en: "No books yet: admins maintain public books in Word Books; classroom books can be created from the Question Bank.",
                })}
              </p>
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
                <div className="flex gap-2">
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
                    zh: "（无标准音的词用设备朗读兜底，仅练习）",
                    en: "(words without audio fall back to device voice, practice only)",
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
function ResultsPanel({ code }: { code: string }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const resultsQuery = useQuery({
    queryKey: ["vocab-teacher", code, "results"],
    queryFn: () =>
      VocabularyService.readVocabResults({ code: code.toUpperCase() }),
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
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">
          {t({
            zh: "还没有进行中的词汇任务，先到「发布任务」安排一期。",
            en: "No vocabulary task in progress yet — assign one first.",
          })}
        </CardContent>
      </Card>
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
          <Button
            variant="outline"
            size="sm"
            disabled={archive.isPending}
            onClick={() => archive.mutate(assignment.id)}
          >
            <Archive />
            {t({ zh: "结束任务", en: "End task" })}
          </Button>
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
