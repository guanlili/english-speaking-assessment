import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Loader2, Plus } from "lucide-react"
import { useState } from "react"
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
import { NumberInput } from "@/components/ui/number-input"
import { AiDraftPanel } from "@/components/Vocabulary/AiDraftPanel"
import { useI18n } from "@/lib/i18n"
import {
  TERMS,
  VOCAB_LEVEL_LABELS,
  VOCAB_LEVEL_ORDER,
  type VocabLevel,
} from "@/lib/terms"
import { AddWordsToBook } from "./AddWordsToBook"
import { CreateClassroomBook } from "./CreateClassroomBook"

const MAX_PUBLISH_WORDS = 100

/** 发布面板：选词库（可现场新建班级词库）→ 勾词 → 预览题量 → 发布快照 */
export function AssignPanel({
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
  // 按实际难度筛选词条（五级词库；未命中分级的词只在「全部」出现）
  const [levelFilter, setLevelFilter] = useState<string>("all")
  const detailQuery = useQuery({
    queryKey: ["vocab-teacher", "book", bookId, levelFilter],
    queryFn: () =>
      VocabularyService.readBook({
        bookId: bookId as string,
        level: levelFilter === "all" ? undefined : levelFilter,
      }),
    enabled: bookId !== null,
  })
  const words = detailQuery.data?.words ?? []

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [title, setTitle] = useState("")
  const [meaningPrompt, setMeaningPrompt] = useState(true)
  const [audioPrompt, setAudioPrompt] = useState(false)
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
                    zh: `勾选要考的词（已选 ${selectedCount}/${activeCount}）`,
                    en: `Pick words to test (${selectedCount}/${activeCount} selected)`,
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
