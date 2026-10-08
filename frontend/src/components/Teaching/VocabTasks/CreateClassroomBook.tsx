import { useMutation } from "@tanstack/react-query"
import { Loader2, Upload } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { ApiError, VocabLevelsService, VocabularyService } from "@/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useI18n } from "@/lib/i18n"
import {
  VOCAB_LEVEL_LABELS,
  VOCAB_LEVEL_ORDER,
  type VocabLevel,
} from "@/lib/terms"
import { localizeImportIssue } from "@/lib/vocabImport"
import type { VocabCsvPreview } from "./types"

/** 新建班级词库：标题 + 可选 CSV 预览导入，绑定当前课堂（scope=classroom）。 */
export function CreateClassroomBook({
  classroomId,
  onCreated,
}: {
  classroomId: string | null
  onCreated: (bookId: string) => void
}) {
  const { t } = useI18n()
  const fileRef = useRef<HTMLInputElement>(null)
  const [title, setTitle] = useState("")
  // 从五级词库导入：只取已核对且有释义的词条（未核对/缺释义自动跳过）
  const [fromLevel, setFromLevel] = useState<VocabLevel | null>(null)
  const fromLevels = useMutation({
    // 续导口径：服务端每次先排除已入库词再限量 → offset 恒为 0 循环拉完
    mutationFn: async () => {
      let totalCreated = 0
      let totalSkipped = 0
      let bookId: string | null = null
      let finalBookId = ""
      for (let round = 0; round < 40; round += 1) {
        const data = await VocabLevelsService.importWordsFromLevels({
          requestBody: {
            level: fromLevel as string,
            classroom_id: bookId ? null : classroomId,
            book_id: bookId,
            new_book_title: title.trim() || null,
          },
        })
        totalCreated += data.created_count ?? 0
        totalSkipped += data.skipped_existing ?? 0
        bookId = data.id
        finalBookId = data.id
        if (
          (data.remaining_count ?? 0) === 0 ||
          (data.created_count ?? 0) === 0
        )
          break
      }
      return { id: finalBookId, totalCreated, totalSkipped }
    },
    onSuccess: (book) => {
      toast.success(
        t({
          zh: `已从五级词库转入 ${book.totalCreated ?? 0} 个已核对词条（跳过 ${book.totalSkipped ?? 0} 个已有词）。`,
          en: `Imported ${book.totalCreated ?? 0} reviewed entries from the leveled source (skipped ${book.totalSkipped ?? 0} existing).`,
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
                zh: "导入失败，请重试。",
                en: "Import failed — please retry.",
              }),
        )
      }
    },
  })
  const [preview, setPreview] = useState<VocabCsvPreview | null>(null)

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
      <div className="space-y-2">
        <label htmlFor="from-level-select" className="text-sm font-medium">
          {t({
            zh: "从五级词库导入（可选）",
            en: "Import from leveled source (optional)",
          })}
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <select
            id="from-level-select"
            value={fromLevel ?? ""}
            onChange={(event) =>
              setFromLevel((event.target.value || null) as VocabLevel | null)
            }
            className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
          >
            <option value="">{t({ zh: "不导入", en: "Don't import" })}</option>
            {VOCAB_LEVEL_ORDER.map((level) => (
              <option key={level} value={level}>
                {t(VOCAB_LEVEL_LABELS[level])}
                {t({ zh: "（仅已核对词条）", en: " (reviewed only)" })}
              </option>
            ))}
          </select>
          {fromLevel && (
            <Button
              size="sm"
              disabled={fromLevels.isPending}
              onClick={() => fromLevels.mutate()}
            >
              {fromLevels.isPending ? (
                <Loader2 className="animate-spin" />
              ) : null}
              {t({ zh: "建库并导入", en: "Create & import" })}
            </Button>
          )}
          <span className="text-xs text-muted-foreground">
            {t({
              zh: "只转入已人工核对且有释义的词条；词库管理页可继续核对其余词条。",
              en: "Only reviewed entries with meanings are imported; review the rest in Word Books admin.",
            })}
          </span>
        </div>
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
