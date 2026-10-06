import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import {
  ArrowLeft,
  BookA,
  GraduationCap,
  LibraryBig,
  Search,
  UsersRound,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import type { VocabularyBookPublic } from "@/client"
import { ApiError, VocabularyService } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
import StudentShell from "@/components/Practice/StudentShell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { APP_NAME } from "@/config"
import { useStudentGuard } from "@/hooks/useStudentGuard"
import { loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN_MIX_WRONG, TERMS } from "@/lib/terms"

export const Route = createFileRoute("/vocab/$code/books")({
  component: VocabBooksPage,
  head: () => ({
    meta: [{ title: `词库浏览 / Word Books - ${APP_NAME}` }],
  }),
})

/** 词数选项（默认 20；词库不足时按实际数量出题） */
const WORD_COUNT_OPTIONS = [10, 20, 30, 50] as const
/** 词条列表一次最多渲染行数（词库最大 500 词，滚动列表截断展示） */
const WORD_LIST_RENDER_LIMIT = 100

function VocabBooksPage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/vocab/$code/books" })
  const navigate = useNavigate({ from: "/vocab/$code/books" })
  const queryClient = useQueryClient()
  const student = loadStudent(code)

  const [bookSearch, setBookSearch] = useState("")
  const [debouncedBookSearch, setDebouncedBookSearch] = useState("")
  const [wordSearch, setWordSearch] = useState("")
  const [debouncedWordSearch, setDebouncedWordSearch] = useState("")
  const [selectedBookId, setSelectedBookId] = useState<string | null>(null)
  const [wordCount, setWordCount] = useState<number>(20)
  const [mixWrong, setMixWrong] = useState(false)

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedBookSearch(bookSearch),
      300,
    )
    return () => window.clearTimeout(timer)
  }, [bookSearch])
  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedWordSearch(wordSearch),
      300,
    )
    return () => window.clearTimeout(timer)
  }, [wordSearch])

  const booksQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: [
      "vocab",
      code,
      "student-books",
      debouncedBookSearch,
      student?.id,
    ],
    queryFn: () =>
      VocabularyService.listStudentBooks({
        code: code.toUpperCase(),
        search: debouncedBookSearch.trim() || undefined,
      }),
    enabled: student !== null,
  })

  const books = useMemo<VocabularyBookPublic[]>(
    () => booksQuery.data ?? [],
    [booksQuery.data],
  )
  const selectedBook = books.find((b) => b.id === selectedBookId) ?? null

  const wordsQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: [
      "vocab",
      code,
      "student-book",
      selectedBookId,
      debouncedWordSearch,
      student?.id,
    ],
    queryFn: () =>
      VocabularyService.readStudentBook({
        code: code.toUpperCase(),
        bookId: selectedBookId as string,
        search: debouncedWordSearch.trim() || undefined,
      }),
    enabled: student !== null && selectedBookId !== null,
  })
  const bookWords = wordsQuery.data?.words ?? []

  useStudentGuard(code, student, booksQuery)
  // 选中词库被过滤掉（如归档）时清空选择
  useEffect(() => {
    if (selectedBookId && books.length > 0 && !selectedBook) {
      setSelectedBookId(null)
      setWordSearch("")
    }
  }, [books.length, selectedBook, selectedBookId])

  const startPractice = useMutation({
    mutationFn: () =>
      VocabularyService.startStudentSession({
        code: code.toUpperCase(),
        requestBody: {
          kind: "self",
          book_id: selectedBookId,
          word_count: wordCount,
          mix_wrong: mixWrong,
        },
      }),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["vocab", code] })
      void navigate({
        to: "/vocab/$code/self",
        params: { code },
        search: { session: (data as { session_id: string }).session_id },
      })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 403) {
        toast.error(
          t({
            zh: "没有权限使用这个词库。",
            en: "You don't have access to this word book.",
          }),
        )
      } else {
        toast.error(
          t({
            zh: "暂时不能开始练习，请稍后再试。",
            en: "Can't start practice right now — please try again.",
          }),
        )
      }
    },
  })

  if (student === null) return null

  // 开始前的实际词数预告：min(设定词数, 词库可用词数)
  const availableCount = selectedBook ? (wordsQuery.data?.word_count ?? 0) : 0
  const plannedCount = Math.min(wordCount, availableCount)

  return (
    <StudentShell active="vocab" wide>
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/vocab/$code" params={{ code }}>
              <ArrowLeft />
              {t({ zh: "返回词汇学习", en: "Back to Vocabulary" })}
            </Link>
          </Button>
          <p className="text-xs text-muted-foreground">
            {t({
              zh: "自主练习与老师任务分开记录，不会互相影响。",
              en: "Self practice is recorded separately from teacher tasks.",
            })}
          </p>
        </div>

        <section className="rounded-3xl border border-primary/10 bg-secondary/40 p-6 sm:p-8">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            {t({ zh: "词库浏览", en: "Word Books" })}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {t({
              zh: "选择公共词库或本班词库，挑一本开始拼写练习。",
              en: "Pick a public or class word book and start spelling practice.",
            })}
          </p>
        </section>

        <div className="relative">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={bookSearch}
            onChange={(event) => setBookSearch(event.target.value)}
            placeholder={t({
              zh: "搜索词库名称…",
              en: "Search word books…",
            })}
            aria-label={t({ zh: "搜索词库名称", en: "Search word books" })}
            className="h-12 pl-9 text-base"
          />
        </div>

        {booksQuery.isPending ? (
          <div role="status" className="space-y-3">
            <span className="sr-only">
              {t({ zh: "正在加载词库…", en: "Loading word books…" })}
            </span>
            <Skeleton className="h-20 rounded-2xl" />
            <Skeleton className="h-20 rounded-2xl" />
          </div>
        ) : booksQuery.isError ? (
          <Card className="items-center px-6 py-10 text-center">
            <BookA className="size-8 text-primary" />
            <p role="alert" className="mt-3 text-sm text-muted-foreground">
              {t({
                zh: "词库暂时没有加载成功，请重试。",
                en: "Word books failed to load — please retry.",
              })}
            </p>
            <Button
              className="mt-4"
              onClick={() => void booksQuery.refetch()}
              disabled={booksQuery.isFetching}
            >
              {t({ zh: "重新加载", en: "Reload" })}
            </Button>
          </Card>
        ) : books.length === 0 ? (
          <Card className="items-center px-6 py-10 text-center">
            <LibraryBig className="size-8 text-muted-foreground" />
            <p className="mt-3 text-sm text-muted-foreground">
              {bookSearch.trim()
                ? t({
                    zh: "没有找到名称匹配的词库，换个关键词试试。",
                    en: "No word book matches that name — try another keyword.",
                  })
                : t({
                    zh: "还没有可浏览的词库，等老师或管理员添加。",
                    en: "No word books yet — ask your teacher or the admin to add some.",
                  })}
            </p>
          </Card>
        ) : (
          <ul className="grid gap-2 md:grid-cols-2">
            {books.map((book) => {
              const active = book.id === selectedBookId
              return (
                <li key={book.id}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      setSelectedBookId(book.id)
                      setWordSearch("")
                    }}
                    className={`flex w-full items-center gap-3 rounded-2xl border px-4 py-3.5 text-left transition-colors ${
                      active
                        ? "border-primary bg-secondary/50"
                        : "bg-card hover:border-primary/40"
                    }`}
                  >
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
                      <BookA className="size-5" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {book.title}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {book.description ||
                          t({
                            zh: `${book.word_count} 个词`,
                            en: `${book.word_count} words`,
                          })}
                      </span>
                    </span>
                    <Badge
                      variant="outline"
                      className="shrink-0 text-muted-foreground"
                    >
                      {book.scope === "public" ? (
                        <>
                          <GraduationCap className="size-3" />
                          {t({ zh: "公共", en: "Public" })}
                        </>
                      ) : (
                        <>
                          <UsersRound className="size-3" />
                          {t({ zh: "本班", en: "Class" })}
                        </>
                      )}
                    </Badge>
                  </button>
                </li>
              )
            })}
          </ul>
        )}

        {/* 选中词库：库内搜索 + 词条预览 + 开练配置 */}
        {selectedBook && (
          <Card>
            <CardHeader className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-base">
                  {selectedBook.title}
                </CardTitle>
                <Badge variant="outline" className="text-muted-foreground">
                  {t({
                    zh: `共 ${selectedBook.word_count} 个词`,
                    en: `${selectedBook.word_count} words`,
                  })}
                </Badge>
              </div>
              <CardDescription>
                {t({
                  zh: "可以先看看库里的词；拼写练习一次从中抽取。",
                  en: "Preview the words first; a practice round draws from them.",
                })}
              </CardDescription>
              <div className="relative">
                <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={wordSearch}
                  onChange={(event) => setWordSearch(event.target.value)}
                  placeholder={t({
                    zh: "搜库内单词或释义…",
                    en: "Search words or meanings…",
                  })}
                  aria-label={t({
                    zh: "搜索库内单词或释义",
                    en: "Search words or meanings",
                  })}
                  className="h-12 pl-9 text-base"
                />
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              {wordsQuery.isPending ? (
                <div role="status" className="text-sm text-muted-foreground">
                  {t({ zh: "正在加载词条…", en: "Loading words…" })}
                </div>
              ) : bookWords.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {debouncedWordSearch.trim()
                    ? t({
                        zh: "没有匹配的词条，换个关键词试试。",
                        en: "No matching words — try another keyword.",
                      })
                    : t({
                        zh: "这个词库还没有可用词条。",
                        en: "This word book has no usable words yet.",
                      })}
                </p>
              ) : (
                <div>
                  <p className="mb-2 text-xs text-muted-foreground">
                    {t({
                      zh: `匹配 ${bookWords.length} 个词${bookWords.length > WORD_LIST_RENDER_LIMIT ? `（仅显示前 ${WORD_LIST_RENDER_LIMIT} 个）` : ""}`,
                      en: `${bookWords.length} match${bookWords.length > WORD_LIST_RENDER_LIMIT ? ` (showing first ${WORD_LIST_RENDER_LIMIT})` : ""}`,
                    })}
                  </p>
                  <ul className="grid gap-1.5 sm:grid-cols-2">
                    {bookWords.slice(0, WORD_LIST_RENDER_LIMIT).map((word) => (
                      <li
                        key={word.id}
                        className="min-w-0 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-xl border px-3 py-2"
                      >
                        {/* 长词可换行（break-all），不把行撑出容器 */}
                        <span className="max-w-full break-all text-sm font-semibold">
                          {word.headword}
                        </span>
                        {word.part_of_speech && (
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {word.part_of_speech}
                          </span>
                        )}
                        <span className="min-w-0 flex-1 basis-24 truncate text-sm text-muted-foreground">
                          {word.meaning_zh}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 开练配置 */}
              {availableCount > 0 && (
                <div className="space-y-4 rounded-2xl bg-secondary/40 p-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <label
                      htmlFor="self-word-count"
                      className="text-sm font-medium"
                    >
                      {t({ zh: "练习词数", en: "Words this round" })}
                    </label>
                    <Select
                      value={String(wordCount)}
                      onValueChange={(value) => setWordCount(Number(value))}
                    >
                      <SelectTrigger
                        id="self-word-count"
                        className="h-11 w-28 text-base"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {WORD_COUNT_OPTIONS.map((count) => (
                          <SelectItem key={count} value={String(count)}>
                            {count}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      {plannedCount < wordCount
                        ? t({
                            zh: `词库只有 ${availableCount} 个词，本轮将练习全部 ${plannedCount} 个。`,
                            en: `Only ${availableCount} words in this book — the round will use all ${plannedCount}.`,
                          })
                        : t({
                            zh: `本轮将练习 ${plannedCount} 个词。`,
                            en: `This round will practice ${plannedCount} words.`,
                          })}
                    </p>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <Checkbox
                      id="mix-wrong"
                      checked={mixWrong}
                      onCheckedChange={(checked) =>
                        setMixWrong(checked === true)
                      }
                      className="mt-0.5"
                    />
                    <div className="min-w-0">
                      <label
                        htmlFor="mix-wrong"
                        className="text-sm font-medium"
                      >
                        {t(TERMS.mixWrongWords)}
                        <InfoHint label={t(EXPLAIN_MIX_WRONG)} />
                      </label>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {t({
                          zh: "只混入本词库里你拼错过的词，最近错的优先。",
                          en: "Only words you previously misspelled in this book, most recent misses first.",
                        })}
                      </p>
                    </div>
                  </div>
                  <Button
                    onClick={() => startPractice.mutate()}
                    disabled={startPractice.isPending}
                    className="h-12 w-full sm:w-auto"
                  >
                    {startPractice.isPending
                      ? t({ zh: "正在开轮…", en: "Starting…" })
                      : t({ zh: "开始练习", en: "Start Practice" })}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        <p className="pb-4 text-center text-xs text-muted-foreground">
          {t({
            zh: "自主练习的成绩只进「练习记录」，不影响老师任务。",
            en: "Self-practice results go to Practice Records only — teacher tasks are untouched.",
          })}
        </p>
      </div>
    </StudentShell>
  )
}
