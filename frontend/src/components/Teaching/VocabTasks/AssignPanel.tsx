import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Loader2, Plus } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { ApiError, StudentsService, VocabularyService } from "@/client"
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
import { NumberInput } from "@/components/ui/number-input"
import { AiDraftPanel } from "@/components/Vocabulary/AiDraftPanel"
import { useI18n } from "@/lib/i18n"
import {
  TERMS,
  VOCAB_LEVEL_LABELS,
  VOCAB_LEVEL_ORDER,
  VOCAB_PROMPT_META,
  type VocabLevel,
} from "@/lib/terms"
import {
  countEligibleByPromptType,
  MIN_CHOICE_WORDS,
} from "@/lib/vocab-prompt-availability"
import {
  CODE_NOT_APPROVED,
  countNotApproved,
  isPublishableWord,
  parseDetailCount,
  reviewStatusLabel,
} from "@/lib/vocabContentReview"
import { AddWordsToBook } from "./AddWordsToBook"
import { CreateClassroomBook } from "./CreateClassroomBook"

const MAX_PUBLISH_WORDS = 100

/** 发布面板：选词库（可现场新建班级词库）→ 勾词 → 预览题量 → 发布快照 */
export function AssignPanel({
  code,
  classroomId,
  onGoReview,
}: {
  code: string
  classroomId: string | null
  onGoReview?: () => void
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
  // 按实际难度筛选词条（五级词库；未命中分级的词只在「全部」出现）
  const [levelFilter, setLevelFilter] = useState<string>("all")
  const detailQuery = useQuery({
    queryKey: ["vocab-teacher", "book", bookId, levelFilter],
    queryFn: () =>
      VocabularyService.readBook({
        book_id: bookId as string,
        level: levelFilter === "all" ? undefined : levelFilter,
      }),
    enabled: bookId !== null,
  })
  const words = detailQuery.data?.words ?? []
  // 发布门禁：只有 approved 且未归档的词条可勾选发布；其余灰色展示并标状态
  const publishableWords = words.filter(isPublishableWord)
  const notApprovedCount = countNotApproved(words)

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [title, setTitle] = useState("")
  const [meaningPrompt, setMeaningPrompt] = useState(true)
  const [audioPrompt, setAudioPrompt] = useState(false)
  // 第一批四类玩法：勾上就真实出题；素材不足时后端 422，不静默出空题
  const [enZhPrompt, setEnZhPrompt] = useState(false)
  const [zhEnPrompt, setZhEnPrompt] = useState(false)
  const [clozePrompt, setClozePrompt] = useState(false)
  const [rootsPrompt, setRootsPrompt] = useState(false)
  // 派发范围：全班 或 手动分组（只发给勾中的学生）
  const [scope, setScope] = useState<"all" | "selected">("all")
  const [selectedStudents, setSelectedStudents] = useState<Set<string>>(
    new Set(),
  )
  const rosterQuery = useQuery({
    queryKey: ["students", classroomId],
    queryFn: () =>
      StudentsService.listStudents({
        classroom_id: classroomId as string,
      }),
    enabled: classroomId !== null,
  })
  const roster = rosterQuery.data ?? []
  const [dueLocal, setDueLocal] = useState("")
  const [showCreateBook, setShowCreateBook] = useState(false)
  // 测验模式：限时 + 及格线 + 可选开放时间（服务端强约束）
  const [isQuiz, setIsQuiz] = useState(false)
  const [durationMinutes, setDurationMinutes] = useState(30)
  const [passLine, setPassLine] = useState(60)
  const [opensLocal, setOpensLocal] = useState("")

  const selectBook = (id: string | null) => {
    setBookId(id)
    setSelected(new Set())
    setTitle("")
    setLevelFilter("all")
  }
  const toggleAll = (checked: boolean) => {
    setSelected(
      checked ? new Set(publishableWords.map((w) => w.id)) : new Set(),
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
        vocabularyAssignmentCreate: {
          title: title.trim() || null,
          word_ids: Array.from(selected),
          prompt_types: promptTypes,
          student_ids:
            scope === "selected" ? Array.from(selectedStudents) : undefined,
          due_at: dueLocal ? new Date(dueLocal).toISOString() : null,
          mode: isQuiz ? "quiz" : "practice",
          duration_minutes: isQuiz ? durationMinutes : null,
          pass_line: isQuiz ? passLine : 60,
          opens_at: opensLocal ? new Date(opensLocal).toISOString() : null,
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
        const detail =
          typeof error.body === "object" && error.body !== null
            ? ((error.body as { detail?: unknown }).detail ?? error.message)
            : error.message
        if (error.status === 422) {
          const notApproved = parseDetailCount(detail, CODE_NOT_APPROVED)
          if (notApproved !== null) {
            toast.error(
              t({
                zh: `有 ${notApproved} 个词条尚未通过审核，不能发布；请先在「词库审核」中通过。`,
                en: `${notApproved} selected words are not approved yet — approve them in Review before publishing.`,
              }),
            )
            return
          }
          toast.error(
            t({
              zh: "发布内容有误：请检查所选词数、出题方式与派发名单（语境填空需例句、词根拼装需词法、四选一至少 4 词、纯听音需全部有标准音）。",
              en: "Cannot publish: check words, prompt types and roster (cloze needs examples, Word Parts needs morphology, choice needs 4+ words, audio-only needs standard audio).",
            }),
          )
          return
        }
        if (error.status === 403) {
          toast.error(
            t({
              zh: "没有权限使用这些词条，请从自己的词库重新选择。",
              en: "No permission to use some of these words — pick from your own books.",
            }),
          )
          return
        }
        toast.error(
          t({
            zh: "发布失败，请重试。",
            en: "Publish failed — please retry.",
          }),
        )
      } else {
        toast.error(
          t({
            zh: "网络异常，发布未完成，请检查连接后重试。",
            en: "Network error — publish didn't go through. Check your connection and retry.",
          }),
        )
      }
    },
  })

  const selectedCount = selected.size
  const publishableCount = publishableWords.length
  const selectedWords = words.filter((word) => selected.has(word.id))
  const eligibleByType = countEligibleByPromptType(selectedWords)
  const promptAvailability = {
    en_zh: selectedCount >= MIN_CHOICE_WORDS,
    zh_en: selectedCount >= MIN_CHOICE_WORDS,
    cloze: eligibleByType.cloze > 0,
    roots: eligibleByType.roots > 0,
  }
  // 素材不足的题型直接禁用并取消勾选，避免提交后才收到笼统的 422
  useEffect(() => {
    if (!promptAvailability.en_zh) setEnZhPrompt(false)
    if (!promptAvailability.zh_en) setZhEnPrompt(false)
    if (!promptAvailability.cloze) setClozePrompt(false)
    if (!promptAvailability.roots) setRootsPrompt(false)
  }, [
    promptAvailability.en_zh,
    promptAvailability.zh_en,
    promptAvailability.cloze,
    promptAvailability.roots,
  ])

  const promptTypes = [
    ...(meaningPrompt ? ["meaning"] : []),
    ...(audioPrompt ? ["audio"] : []),
    ...(enZhPrompt ? ["en_zh"] : []),
    ...(zhEnPrompt ? ["zh_en"] : []),
    ...(clozePrompt ? ["cloze"] : []),
    ...(rootsPrompt ? ["roots"] : []),
  ]
  const scopeReady = scope === "all" || selectedStudents.size > 0
  const canPublish =
    selectedCount > 0 &&
    selectedCount <= MAX_PUBLISH_WORDS &&
    promptTypes.length > 0 &&
    scopeReady &&
    !(isQuiz && !(durationMinutes >= 5 && durationMinutes <= 240)) &&
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
                    zh: `勾选要考的词（已选 ${selectedCount}/${publishableCount}）`,
                    en: `Pick words to test (${selectedCount}/${publishableCount} selected)`,
                  })}
                </p>
                <div className="flex flex-wrap gap-2">
                  <select
                    value={levelFilter}
                    onChange={(event) => {
                      setLevelFilter(event.target.value)
                      setSelected(new Set())
                    }}
                    aria-label={t({ zh: "按级别筛选", en: "Filter by level" })}
                    className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
                  >
                    <option value="all">
                      {t({ zh: "全部级别", en: "All levels" })}
                    </option>
                    {VOCAB_LEVEL_ORDER.map((level) => (
                      <option key={level} value={level}>
                        {t(VOCAB_LEVEL_LABELS[level])}
                      </option>
                    ))}
                  </select>
                  {detailQuery.data?.scope === "classroom" ? (
                    // key=bookId：切换词库即重挂载，清掉未确认的 CSV 预览，
                    // 防止 A 库的预览词条被确认进 B 库（飞行中的预览请求
                    // 回来后 setState 到已卸载组件是 no-op，同样安全）
                    <AddWordsToBook
                      key={bookId}
                      bookId={bookId}
                      beforeWordCount={detailQuery.data?.word_count ?? null}
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
              {publishableCount === 0 && words.length === 0 && (
                <p role="status" className="text-sm text-muted-foreground">
                  {t({
                    zh: "这个词库还没有词：点上面的「CSV 加词」导入，或回到第一步新建词库。",
                    en: "This book is empty — import via “Add words via CSV” above, or go back and create a book.",
                  })}
                </p>
              )}
              {notApprovedCount > 0 && (
                <div className="flex flex-wrap items-center gap-2 rounded-xl border border-amber-300/50 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-950/20 dark:text-amber-200">
                  <span>
                    {t({
                      zh: `还有 ${notApprovedCount} 个词条未通过审核，不能发布。`,
                      en: `${notApprovedCount} words are not approved yet and can't be published.`,
                    })}
                  </span>
                  {onGoReview && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-amber-900 dark:text-amber-200"
                      onClick={onGoReview}
                    >
                      {t({ zh: "去审核", en: "Go to Review" })}
                    </Button>
                  )}
                </div>
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
                {publishableWords.map((word) => (
                  <label
                    key={word.id}
                    className={`flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors ${
                      selected.has(word.id)
                        ? "bg-secondary text-foreground"
                        : "text-muted-foreground hover:bg-secondary/50"
                    }`}
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
                      {word.level && (
                        <Badge
                          variant="outline"
                          className="ml-1.5 shrink-0 text-[10px]"
                        >
                          {t(
                            VOCAB_LEVEL_LABELS[word.level as VocabLevel] ?? {
                              zh: word.level,
                              en: word.level,
                            },
                          )}
                        </Badge>
                      )}
                    </span>
                  </label>
                ))}
                {words
                  .filter((word) => !isPublishableWord(word))
                  .map((word) => (
                    <div
                      key={word.id}
                      className="flex min-h-11 items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm opacity-60"
                      aria-disabled="true"
                    >
                      <input
                        type="checkbox"
                        disabled
                        checked={false}
                        className="size-4 accent-[var(--primary)]"
                        readOnly
                      />
                      <span className="min-w-0 flex-1 truncate">
                        <span className="font-semibold">{word.headword}</span>
                        <span className="ml-2 text-muted-foreground">
                          {word.meaning_zh}
                        </span>
                      </span>
                      <Badge variant="outline">
                        {t(reviewStatusLabel(word.review_status))}
                      </Badge>
                    </div>
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
          <div className="space-y-3 rounded-2xl border border-primary/15 bg-secondary/30 p-4">
            <p className="text-sm font-medium">
              {t({ zh: "任务模式", en: "Task mode" })}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant={!isQuiz ? "default" : "outline"}
                aria-pressed={!isQuiz}
                onClick={() => setIsQuiz(false)}
              >
                {t({ zh: "练习（可重试）", en: "Practice (retries allowed)" })}
              </Button>
              <Button
                type="button"
                size="sm"
                variant={isQuiz ? "default" : "outline"}
                aria-pressed={isQuiz}
                onClick={() => setIsQuiz(true)}
              >
                {t(TERMS.vocabQuiz)}
              </Button>
            </div>
            {isQuiz && (
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="space-y-2">
                  <label
                    htmlFor="quiz-duration"
                    className="text-sm font-medium"
                  >
                    {t(TERMS.quizDuration)}
                  </label>
                  <select
                    id="quiz-duration"
                    value={String(durationMinutes)}
                    onChange={(event) =>
                      setDurationMinutes(Number(event.target.value))
                    }
                    className="h-11 w-full max-w-xs rounded-xl border border-input bg-card px-3 text-base text-foreground"
                  >
                    {[10, 15, 20, 30, 45, 60, 90, 120].map((minutes) => (
                      <option key={minutes} value={minutes}>
                        {minutes} {t({ zh: "分钟", en: "min" })}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  <label
                    htmlFor="quiz-pass-line"
                    className="text-sm font-medium"
                  >
                    {t(TERMS.passLine)}
                  </label>
                  <NumberInput
                    id="quiz-pass-line"
                    min={0}
                    max={100}
                    value={passLine}
                    onValueChange={(v) =>
                      setPassLine(Math.max(0, Math.min(100, v)))
                    }
                    className="max-w-xs"
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="quiz-opens" className="text-sm font-medium">
                    {t({ zh: "开放时间（可选）", en: "Open time (optional)" })}
                  </label>
                  <Input
                    id="quiz-opens"
                    type="datetime-local"
                    value={opensLocal}
                    onChange={(event) => setOpensLocal(event.target.value)}
                    className="h-11 max-w-xs text-base"
                  />
                </div>
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              {isQuiz
                ? t({
                    zh: "测验：学生在规则页点「开始测验」才计时（服务器计时，刷新/换设备不重置）；每题只能提交一次；到时自动交卷；默认一次参与，可单独授权补考；成绩与答案由你分别公布。",
                    en: "Quiz: the timer starts only when the student taps Start (server time; refresh/device switch won't reset). One submission per item; auto-submit at time-up. One attempt by default, retakes granted per student; grades and answers are published separately.",
                  })
                : t({
                    zh: "练习：可反复重试，统计按每题第一次作答计。",
                    en: "Practice: retries allowed; stats count each item's first answer.",
                  })}
            </p>
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
                  <span className="text-xs text-muted-foreground">
                    {isQuiz
                      ? t({
                          zh: "（测验含听音时要求全部词有稳定标准音，浏览器语音不能作题源）",
                          en: "(quizzes with audio need standard audio for every word — device voice can't be a question source)",
                        })
                      : t({
                          zh: "（无标准音的词自动走看义；纯听音任务要求全部词有标准音）",
                          en: "(words without audio fall back to meaning; audio-only tasks need audio for every word)",
                        })}
                  </span>
                </span>
              </label>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {(
                [
                  ["en_zh", enZhPrompt, setEnZhPrompt],
                  ["zh_en", zhEnPrompt, setZhEnPrompt],
                  ["cloze", clozePrompt, setClozePrompt],
                  ["roots", rootsPrompt, setRootsPrompt],
                ] as const
              ).map(([type, checked, setChecked]) => {
                const available = promptAvailability[type]
                return (
                  <label
                    key={type}
                    className={`flex min-h-14 items-start gap-2 rounded-xl border bg-card px-3 py-2.5 text-sm ${
                      available
                        ? "cursor-pointer"
                        : "cursor-not-allowed opacity-60"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!available}
                      onChange={(event) => setChecked(event.target.checked)}
                      className="mt-1 size-4 accent-[var(--primary)]"
                    />
                    <span className="min-w-0">
                      <span className="block font-medium">
                        {t(VOCAB_PROMPT_META[type].label)}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {available
                          ? t(VOCAB_PROMPT_META[type].hint)
                          : type === "roots"
                            ? t({
                                zh: "所选词没有可用的词法拆解，补词法后再选。",
                                en: "The selected words have no usable morphology yet — add it first.",
                              })
                            : type === "cloze"
                              ? t({
                                  zh: "所选词没有含原词的例句，补例句后再选。",
                                  en: "The selected words have no example containing the word — add examples first.",
                                })
                              : t({
                                  zh: `四选一至少需要 ${MIN_CHOICE_WORDS} 个词。`,
                                  en: `Choice questions need at least ${MIN_CHOICE_WORDS} words.`,
                                })}
                      </span>
                    </span>
                  </label>
                )
              })}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {t({
                zh: "四类玩法可选一种或多种；语境填空需要词条带例句，词根拼装需要词条带词法拆解，四选一至少需要 4 个词。素材不足时发布会明确拒绝，不会出空题。",
                en: "Pick one or more of the four modes. Cloze needs example sentences, Word Parts needs morphology, and multiple-choice needs at least 4 words. Publishing is rejected when material is missing — no empty items.",
              })}
            </p>
          </div>

          <div className="space-y-3">
            <p className="text-sm font-medium">
              5. {t({ zh: "派发范围", en: "Who gets it" })}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant={scope === "all" ? "default" : "outline"}
                onClick={() => setScope("all")}
              >
                {t({ zh: "全班", en: "Whole class" })}
              </Button>
              <Button
                type="button"
                size="sm"
                variant={scope === "selected" ? "default" : "outline"}
                onClick={() => setScope("selected")}
              >
                {t({ zh: "指定学生（手动分组）", en: "Selected students" })}
              </Button>
            </div>
            {scope === "selected" && (
              <div className="rounded-2xl border bg-card p-3">
                {classroomId === null ? (
                  <p className="text-xs text-muted-foreground">
                    {t({
                      zh: "先在班级页进入本班后再发布。",
                      en: "Open this class first, then publish.",
                    })}
                  </p>
                ) : roster.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    {t({
                      zh: "本班还没有学生；先让学生入班，或改为全班派发。",
                      en: "No students in this class yet — add students first, or dispatch to the whole class.",
                    })}
                  </p>
                ) : (
                  <>
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <button
                        type="button"
                        className="rounded-lg border px-2 py-1"
                        onClick={() =>
                          setSelectedStudents(
                            new Set(roster.map((row) => row.student.id)),
                          )
                        }
                      >
                        {t({ zh: "全选", en: "Select all" })}
                      </button>
                      <button
                        type="button"
                        className="rounded-lg border px-2 py-1"
                        onClick={() => setSelectedStudents(new Set())}
                      >
                        {t({ zh: "清空", en: "Clear" })}
                      </button>
                      <span>
                        {t({
                          zh: `已选 ${selectedStudents.size}/${roster.length} 人`,
                          en: `${selectedStudents.size}/${roster.length} selected`,
                        })}
                      </span>
                    </div>
                    <ul className="grid max-h-56 gap-1 overflow-y-auto sm:grid-cols-2">
                      {roster.map((row) => {
                        const studentId = row.student.id
                        const checked = selectedStudents.has(studentId)
                        return (
                          <li key={studentId}>
                            <label className="flex min-h-11 cursor-pointer items-center gap-2 rounded-lg px-2 text-sm hover:bg-secondary/60">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={(event) => {
                                  setSelectedStudents((prev) => {
                                    const next = new Set(prev)
                                    if (event.target.checked)
                                      next.add(studentId)
                                    else next.delete(studentId)
                                    return next
                                  })
                                }}
                                className="size-4 accent-[var(--primary)]"
                              />
                              {row.student.display_name}
                            </label>
                          </li>
                        )
                      })}
                    </ul>
                    {selectedStudents.size === 0 && (
                      <p className="mt-2 text-xs text-destructive">
                        {t({
                          zh: "至少选一名学生，否则无法发布。",
                          en: "Select at least one student to publish.",
                        })}
                      </p>
                    )}
                  </>
                )}
              </div>
            )}
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
              {t(
                isQuiz
                  ? {
                      zh: `发布测验（${selectedCount} 词）`,
                      en: `Publish quiz (${selectedCount} words)`,
                    }
                  : {
                      zh: `发布（${selectedCount} 词）`,
                      en: `Publish (${selectedCount} words)`,
                    },
              )}
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

      <AiDraftPanel
        bookId={bookId}
        bookTitle={books.find((b) => b.id === bookId)?.title ?? null}
      />
    </div>
  )
}
