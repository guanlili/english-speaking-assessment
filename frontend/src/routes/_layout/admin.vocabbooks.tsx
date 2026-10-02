import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  Archive,
  BookA,
  ChevronRight,
  Download,
  Loader2,
  Plus,
  RefreshCw,
  Upload,
} from "lucide-react"
import { useRef, useState } from "react"
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
import { useI18n } from "@/lib/i18n"
import { localizeImportIssue } from "@/lib/vocabImport"

export const Route = createFileRoute("/_layout/admin/vocabbooks")({
  component: VocabBooksAdmin,
  head: () => ({
    meta: [{ title: `词库管理 / Word Books - ${APP_NAME}` }],
  }),
})

/** CSV 预览行（导入确认用；保留全部支持字段，避免 meaning_en/example_en 静默丢失） */
type PreviewWord = {
  headword: string
  part_of_speech?: string | null
  meaning_zh: string
  meaning_en?: string | null
  accepted_spellings?: Array<string> | null
  example_en?: string | null
}

type PreviewState = {
  rows: PreviewWord[]
  invalid: Array<{ line: number; reason: string }>
  duplicates: Array<{ line: number; reason: string }>
}

function VocabBooksAdmin() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)

  const booksQuery = useQuery({
    queryKey: ["admin", "vocab-books"],
    queryFn: () => VocabularyService.listBooks(),
  })
  const books = booksQuery.data ?? []

  const [openBookId, setOpenBookId] = useState<string | null>(null)
  const detailQuery = useQuery({
    queryKey: ["admin", "vocab-book", openBookId],
    queryFn: () => VocabularyService.readBook({ bookId: openBookId as string }),
    enabled: openBookId !== null,
  })

  // 新建词库（含导入确认）
  const [creating, setCreating] = useState(false)
  const [newTitle, setNewTitle] = useState("")
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const previewFileRef = useRef<HTMLInputElement>(null)

  const importPreview = useMutation({
    mutationFn: (file: File) =>
      VocabularyService.importVocabPreview({
        formData: { file: file as unknown as string },
      }),
    onSuccess: (data) => {
      setPreview({
        rows: (data.rows ?? []).map((row) => ({
          headword: row.word.headword,
          meaning_zh: row.word.meaning_zh,
          part_of_speech: row.word.part_of_speech,
          meaning_en: row.word.meaning_en,
          accepted_spellings: row.word.accepted_spellings,
          example_en: row.word.example_en,
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

  const createBook = useMutation({
    mutationFn: (payload: { title: string; words: PreviewState["rows"] }) =>
      VocabularyService.createBook({
        requestBody: {
          title: payload.title,
          scope: "public",
          description: null,
          words: payload.words,
        },
      }),
    onSuccess: () => {
      toast.success(t({ zh: "词库已创建。", en: "Word book created." }))
      setCreating(false)
      setPreview(null)
      setNewTitle("")
      queryClient.invalidateQueries({ queryKey: ["admin", "vocab-books"] })
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(
          error.status === 403
            ? t({
                zh: "只有管理员能创建公共词库。",
                en: "Only admins can create public books.",
              })
            : t({
                zh: "创建失败，请重试。",
                en: "Create failed — please retry.",
              }),
        )
      }
    },
  })

  const archiveBook = useMutation({
    mutationFn: (bookId: string) =>
      VocabularyService.updateBook({
        bookId,
        requestBody: { status: "archived" },
      }),
    onSuccess: () => {
      toast.success(t({ zh: "词库已归档。", en: "Book archived." }))
      queryClient.invalidateQueries({ queryKey: ["admin", "vocab-books"] })
    },
  })

  const addWords = useMutation({
    mutationFn: (payload: { bookId: string; words: PreviewState["rows"] }) =>
      VocabularyService.addBookWords({
        bookId: payload.bookId,
        requestBody: payload.words,
      }),
    onSuccess: (data) => {
      toast.success(
        t({
          zh: `已加入 ${data.words?.length ?? 0} 个词条。`,
          en: `Added ${data.words?.length ?? 0} words.`,
        }),
      )
      setPreview(null)
      queryClient.invalidateQueries({ queryKey: ["admin", "vocab-books"] })
      queryClient.invalidateQueries({ queryKey: ["admin", "vocab-book"] })
    },
  })

  const removeWord = useMutation({
    mutationFn: (payload: { bookId: string; wordId: string }) =>
      VocabularyService.removeBookWord({
        bookId: payload.bookId,
        wordId: payload.wordId,
      }),
    onSuccess: () => {
      toast.success(t({ zh: "词条已移除。", en: "Word removed." }))
      queryClient.invalidateQueries({ queryKey: ["admin", "vocab-books"] })
      queryClient.invalidateQueries({ queryKey: ["admin", "vocab-book"] })
    },
  })

  const downloadTemplate = () => {
    downloadCsv(
      [
        [
          "headword",
          "part_of_speech",
          "meaning_zh",
          "meaning_en",
          "accepted_spellings",
          "example_en",
        ],
        [
          "dog",
          "n.",
          "狗",
          "a common pet",
          "",
          "My dog greets me at the door.",
        ],
        [
          "favourite",
          "adj.",
          "最喜欢的",
          "liked more than all others",
          "favorite",
          "Blue is my favourite color.",
        ],
      ],
      "vocab-book-template.csv",
    )
  }

  const openBook = books.find((book) => book.id === openBookId)
  const validRows = preview?.rows ?? []

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t({ zh: "词库管理", en: "Word Books" })}
        </h1>
        <p className="text-muted-foreground">
          {t({
            zh: "维护公共词库供全体教师发布词汇任务；教师也可在班级内自建词库。导入前先预览校验，已归档词库不再出现在发布列表。",
            en: "Maintain public word books for all teachers; teachers can also build classroom books. Preview and validate before importing; archived books no longer appear for publishing.",
          })}
        </p>
      </div>

      {/* 词库列表 */}
      <Card>
        <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="text-base">
              {t({ zh: "全部词库", en: "All word books" })}{" "}
              <span className="text-sm font-normal text-muted-foreground">
                · {books.length}
              </span>
            </CardTitle>
            <CardDescription>
              {t({
                zh: "公共词库由管理员维护；班级词库由本班教师维护。",
                en: "Public books are maintained by admins; classroom books by their teachers.",
              })}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => void booksQuery.refetch()}
              disabled={booksQuery.isFetching}
            >
              <RefreshCw
                className={booksQuery.isFetching ? "animate-spin" : ""}
              />
              {t({ zh: "刷新", en: "Refresh" })}
            </Button>
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus />
              {t({ zh: "新建公共词库", en: "New Public Book" })}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="pb-0">
          {booksQuery.isPending ? (
            <div role="status" className="pb-6">
              <Skeleton className="h-32 rounded-xl" />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t({ zh: "词库", en: "Book" })}</TableHead>
                  <TableHead>{t({ zh: "作用域", en: "Scope" })}</TableHead>
                  <TableHead>{t({ zh: "词数", en: "Words" })}</TableHead>
                  <TableHead>{t({ zh: "状态", en: "Status" })}</TableHead>
                  <TableHead>{t({ zh: "操作", en: "Actions" })}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {books.map((book) => (
                  <TableRow key={book.id}>
                    <TableCell>
                      <span className="font-medium">{book.title}</span>
                      {book.description && (
                        <span className="ml-2 hidden text-xs text-muted-foreground md:inline">
                          {book.description}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      {book.scope === "public" ? (
                        <Badge variant="secondary">
                          {t({ zh: "公共", en: "Public" })}
                        </Badge>
                      ) : (
                        <Badge variant="outline">
                          {t({ zh: "班级", en: "Classroom" })}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {book.word_count ?? 0}
                    </TableCell>
                    <TableCell>
                      {book.status === "active" ? (
                        <span className="text-primary">
                          {t({ zh: "启用", en: "Active" })}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">
                          {t({ zh: "已归档", en: "Archived" })}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setOpenBookId(
                              openBookId === book.id ? null : book.id,
                            )
                          }
                        >
                          <ChevronRight
                            className={
                              openBookId === book.id
                                ? "rotate-90 transition-transform"
                                : "transition-transform"
                            }
                          />
                          {t({ zh: "词条", en: "Words" })}
                        </Button>
                        {book.status === "active" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={archiveBook.isPending}
                            onClick={() => {
                              setOpenBookId(null)
                              archiveBook.mutate(book.id)
                            }}
                          >
                            <Archive />
                            {t({ zh: "归档", en: "Archive" })}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* 词库词条展开区（查看 / 加词 / 移除） */}
      {openBook && (
        <Card>
          <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
            <div>
              <CardTitle className="text-base">
                <BookA className="mr-1.5 inline size-4 text-primary" />
                {openBook.title}{" "}
                <span className="text-sm font-normal text-muted-foreground">
                  · {detailQuery.data?.word_count ?? openBook.word_count ?? 0}{" "}
                  {t({ zh: "词", en: "words" })}
                </span>
              </CardTitle>
              <CardDescription>
                {t({
                  zh: "编辑词条不影响已发布任务（它们按发布快照判分展示）。",
                  en: "Editing words never affects published tasks (they score and display by their snapshots).",
                })}
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={downloadTemplate}>
                <Download />
                {t({ zh: "CSV 模板", en: "CSV Template" })}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => previewFileRef.current?.click()}
                disabled={importPreview.isPending}
              >
                {importPreview.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Upload />
                )}
                {t({ zh: "CSV 加词", en: "Add via CSV" })}
              </Button>
              <input
                ref={previewFileRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) importPreview.mutate(file)
                  event.target.value = ""
                }}
              />
            </div>
          </CardHeader>
          <CardContent className="pb-0">
            {detailQuery.isPending ? (
              <div role="status" className="pb-6">
                <Skeleton className="h-32 rounded-xl" />
              </div>
            ) : (
              <>
                <p className="pb-3 text-xs text-muted-foreground sm:hidden">
                  {t({
                    zh: "横向滑动表格，可以查看完整词条。",
                    en: "Swipe the table sideways to see all fields.",
                  })}
                </p>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t({ zh: "单词", en: "Word" })}</TableHead>
                      <TableHead>{t({ zh: "词性", en: "POS" })}</TableHead>
                      <TableHead>
                        {t({ zh: "中文释义", en: "Chinese meaning" })}
                      </TableHead>
                      <TableHead>
                        {t({ zh: "可接受拼写", en: "Accepted spellings" })}
                      </TableHead>
                      <TableHead>{t({ zh: "操作", en: "Actions" })}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(detailQuery.data?.words ?? []).map((word) => (
                      <TableRow key={word.id}>
                        <TableCell className="font-semibold">
                          {word.headword}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {word.part_of_speech ?? "–"}
                        </TableCell>
                        <TableCell>{word.meaning_zh}</TableCell>
                        <TableCell className="text-muted-foreground">
                          {(word.accepted_spellings ?? []).join(" / ") || "–"}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={removeWord.isPending}
                            onClick={() =>
                              removeWord.mutate({
                                bookId: openBook.id,
                                wordId: word.id,
                              })
                            }
                          >
                            {t({ zh: "移除", en: "Remove" })}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {/* 新建词库（含 CSV 导入预览） */}
      {creating && (
        <Card className="border-primary/30">
          <CardHeader>
            <CardTitle className="text-base">
              {t({ zh: "新建公共词库", en: "New public word book" })}
            </CardTitle>
            <CardDescription>
              {t({
                zh: "可先建空库再手动加词，或直接导入 CSV（先预览校验，确认后入库）。",
                en: "Create it empty and add words later, or import a CSV (previewed and validated before anything is saved).",
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="new-book-title" className="text-sm font-medium">
                {t({ zh: "词库名称", en: "Book title" })}
              </label>
              <Input
                id="new-book-title"
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
                placeholder={t({
                  zh: "如：七年级上 · Unit 1-4",
                  en: "e.g. Grade 7A · Units 1-4",
                })}
                className="h-11 max-w-md text-base"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={downloadTemplate}>
                <Download />
                {t({ zh: "下载 CSV 模板", en: "Download CSV Template" })}
              </Button>
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
                {t({ zh: "选择 CSV 预览", en: "Choose CSV to Preview" })}
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
            </div>

            {preview && (
              <div className="rounded-xl border border-dashed border-primary/40 bg-secondary/40 p-4">
                <p className="text-sm">
                  {t({ zh: "预览：有效 ", en: "Preview: " })}
                  <strong>{validRows.length}</strong>
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
                  {validRows.slice(0, 12).map((row) => (
                    <span
                      key={`${row.headword}-${row.meaning_zh}`}
                      className="rounded bg-secondary px-2 py-0.5 text-xs text-primary"
                    >
                      {row.headword} · {row.meaning_zh}
                    </span>
                  ))}
                  {validRows.length > 12 && (
                    <span className="text-xs text-muted-foreground">
                      {t({
                        zh: `…共 ${validRows.length} 个`,
                        en: `…${validRows.length} in total`,
                      })}
                    </span>
                  )}
                </div>
                {(preview.invalid.length > 0 ||
                  preview.duplicates.length > 0) && (
                  <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">
                    {[...preview.invalid, ...preview.duplicates]
                      .slice(0, 6)
                      .map((issue) => (
                        <li key={`${issue.line}-${issue.reason}`}>
                          {t({ zh: "第", en: "Line" })} {issue.line}{" "}
                          {t({ zh: "行", en: "" })}：
                          {t(localizeImportIssue(issue.reason))}
                        </li>
                      ))}
                  </ul>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={
                      createBook.isPending ||
                      (validRows.length > 0 && newTitle.trim() === "")
                    }
                    onClick={() =>
                      createBook.mutate({
                        title:
                          newTitle.trim() ||
                          t({ zh: "未命名词库", en: "Untitled book" }),
                        words: validRows,
                      })
                    }
                  >
                    {createBook.isPending ? (
                      <Loader2 className="animate-spin" />
                    ) : null}
                    {validRows.length > 0
                      ? t({
                          zh: `确认并创建（含 ${validRows.length} 词）`,
                          en: `Confirm & create (${validRows.length} words)`,
                        })
                      : t({ zh: "创建空词库", en: "Create empty book" })}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setPreview(null)}
                  >
                    {t({ zh: "清除预览", en: "Clear preview" })}
                  </Button>
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3 border-t pt-4">
              <Button
                disabled={createBook.isPending || newTitle.trim() === ""}
                onClick={() =>
                  createBook.mutate({ title: newTitle.trim(), words: [] })
                }
              >
                {createBook.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Plus />
                )}
                {t({ zh: "创建空词库", en: "Create Empty Book" })}
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setCreating(false)
                  setPreview(null)
                  setNewTitle("")
                }}
              >
                {t({ zh: "取消", en: "Cancel" })}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 已有词库的 CSV 加词确认 */}
      {preview && openBook && (
        <Card className="border-primary/30">
          <CardHeader>
            <CardTitle className="text-base">
              {t({
                zh: `向「${openBook.title}」加词`,
                en: `Add words to “${openBook.title}”`,
              })}
            </CardTitle>
            <CardDescription>
              {t({
                zh: "与库内已有的同词同义词会自动跳过，其余按顺序追加。",
                en: "Words already in this book are skipped; the rest are appended in order.",
              })}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={addWords.isPending || validRows.length === 0}
                onClick={() =>
                  addWords.mutate({ bookId: openBook.id, words: validRows })
                }
              >
                {addWords.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : null}
                {t({
                  zh: `确认加入 ${validRows.length} 个词`,
                  en: `Add ${validRows.length} words`,
                })}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setPreview(null)}
              >
                {t({ zh: "取消", en: "Cancel" })}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <p className="pb-6 text-center text-xs text-muted-foreground">
        {t({
          zh: "词库是教学内容，学生的错词与成绩是独立数据：改词库不会清掉学生的历史记录。",
          en: "Books are teaching content; students' wrong words and results are separate data — editing a book never erases their history.",
        })}
      </p>
    </div>
  )
}
