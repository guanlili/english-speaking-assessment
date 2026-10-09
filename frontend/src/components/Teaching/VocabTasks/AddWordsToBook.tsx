import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Loader2, Upload } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { ApiError, VocabularyService } from "@/client"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { localizeImportIssue } from "@/lib/vocabImport"
import type { VocabCsvPreview } from "./types"

/** 向已有班级词库补词：CSV 预览确认后调用 addBookWords（库里已有的自动跳过）。 */
export function AddWordsToBook({
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
