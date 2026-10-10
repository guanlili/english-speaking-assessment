import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Loader2, Sparkles, Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { VocabularyAiWordDraft } from "@/client"
import { ApiError, VocabularyAiService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useI18n } from "@/lib/i18n"
import {
  EXPLAIN_AI_CONTENT,
  TERMS,
  VOCAB_LEVEL_LABELS,
  VOCAB_LEVEL_ORDER,
} from "@/lib/terms"
import { formatDateTime } from "@/lib/time"

interface EditableDraft {
  include: boolean
  headword: string
  part_of_speech: string
  meaning_zh: string
  meaning_en: string
  example_en: string
}

const COUNT_OPTIONS = [5, 10, 15, 20]

/** 教师 AI 词条草稿面板：主题/级别/数量/补充要求 → 生成 → 预览编辑 → 确认入库。
 *  红线：只入词库不发布任务；accepted_spellings 不由 AI 生成。 */
export function AiDraftPanel({
  bookId,
  bookTitle,
}: {
  bookId: string | null
  bookTitle: string | null
}) {
  const { t, lang } = useI18n()
  const queryClient = useQueryClient()
  const [theme, setTheme] = useState("")
  const [level, setLevel] = useState<string>("KET")
  const [count, setCount] = useState(10)
  const [hint, setHint] = useState("")
  const [drafts, setDrafts] = useState<EditableDraft[] | null>(null)
  const [dropped, setDropped] = useState(0)
  const [generatedAt, setGeneratedAt] = useState<string | null>(null)

  const generate = useMutation({
    mutationFn: () =>
      VocabularyAiService.generateWordDrafts({
        requestBody: {
          theme: theme.trim(),
          level,
          count,
          hint: hint.trim() || undefined,
        },
      }),
    onSuccess: (data) => {
      setDropped(data.dropped_count ?? 0)
      setGeneratedAt(data.generated_at ?? null)
      setDrafts(
        (data.drafts ?? []).map((d: VocabularyAiWordDraft) => ({
          include: true,
          headword: d.headword,
          part_of_speech: d.part_of_speech ?? "",
          meaning_zh: d.meaning_zh,
          meaning_en: d.meaning_en ?? "",
          example_en: d.example_en ?? "",
        })),
      )
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 429) {
        toast.error(
          t({
            zh: "AI 生成次数已达上限（每小时 10 次），请稍后再试。",
            en: "AI generation limit reached (10/hour) — retry later.",
          }),
        )
        return
      }
      toast.error(
        t({
          zh: "AI 生成失败：请稍后再试或调整主题与要求。",
          en: "AI generation failed — retry later or adjust the topic.",
        }),
      )
    },
  })

  const importDrafts = useMutation({
    mutationFn: (rows: EditableDraft[]) =>
      VocabularyAiService.importWordDrafts({
        requestBody: {
          book_id: bookId as string,
          drafts: rows.map((row) => ({
            headword: row.headword.trim(),
            part_of_speech: row.part_of_speech.trim() || null,
            meaning_zh: row.meaning_zh.trim(),
            meaning_en: row.meaning_en.trim() || null,
            example_en: row.example_en.trim() || null,
          })),
        },
      }),
    onSuccess: (data) => {
      toast.success(
        t({
          zh: `已加入词库：新增 ${data.added} 个，跳过重复 ${data.skipped} 个。`,
          en: `Added to the book: ${data.added} new, ${data.skipped} duplicates skipped.`,
        }),
      )
      setDrafts(null)
      void queryClient.invalidateQueries({ queryKey: ["vocab-teacher"] })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 403) {
        toast.error(
          t({
            zh: "只能加入你自己班级的词库（公共词库由管理员维护）。",
            en: "Only your own classroom books can be edited.",
          }),
        )
        return
      }
      toast.error(
        t({
          zh: "入库失败，请检查草稿后重试。",
          en: "Import failed — check the drafts and retry.",
        }),
      )
    },
  })

  const included = (drafts ?? []).filter(
    (row) => row.include && row.headword.trim() && row.meaning_zh.trim(),
  )
  const canGenerate = theme.trim().length > 0 && !generate.isPending
  const canImport =
    bookId !== null && included.length > 0 && !importDrafts.isPending

  const updateRow = (index: number, patch: Partial<EditableDraft>) => {
    setDrafts((prev) =>
      (prev ?? []).map((row, i) => (i === index ? { ...row, ...patch } : row)),
    )
  }

  return (
    <Card className="border-primary/20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="size-4 text-primary" />
          {t(TERMS.aiPrep)} · {t({ zh: "词条草稿", en: "Word entry drafts" })}
        </CardTitle>
        <CardDescription>
          {t({
            zh: "AI 只起草，不发布任务：预览、编辑后确认加入词库。可接受拼写变体请之后在词条编辑里手动维护。",
            en: "AI drafts only — nothing is published. Preview, edit, then confirm into a book. Accepted spelling variants are maintained manually afterwards.",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <label htmlFor="ai-theme" className="text-sm font-medium">
              {t({ zh: "主题（必填）", en: "Topic (required)" })}
            </label>
            <Input
              id="ai-theme"
              value={theme}
              maxLength={120}
              onChange={(event) => setTheme(event.target.value)}
              placeholder={t({
                zh: "如：校园生活 / 天气与旅行",
                en: "e.g. school life, weather & travel",
              })}
              className="h-11 text-base"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="ai-level" className="text-sm font-medium">
              {t({ zh: "词汇级别", en: "Level" })}
            </label>
            <Select value={level} onValueChange={setLevel}>
              <SelectTrigger id="ai-level" className="h-11 text-base">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {VOCAB_LEVEL_ORDER.map((lv) => (
                  <SelectItem key={lv} value={lv}>
                    {t(VOCAB_LEVEL_LABELS[lv])}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="ai-count" className="text-sm font-medium">
              {t({ zh: "数量", en: "Count" })}
            </label>
            <Select
              value={String(count)}
              onValueChange={(value) => setCount(Number(value))}
            >
              <SelectTrigger id="ai-count" className="h-11 text-base">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COUNT_OPTIONS.map((c) => (
                  <SelectItem key={c} value={String(c)}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="ai-hint" className="text-sm font-medium">
              {t({ zh: "补充要求（可选）", en: "Extra guidance (optional)" })}
            </label>
            <Input
              id="ai-hint"
              value={hint}
              maxLength={300}
              onChange={(event) => setHint(event.target.value)}
              placeholder={t({
                zh: "如：避免已有的词，偏向动词",
                en: "e.g. avoid duplicates, prefer verbs",
              })}
              className="h-11 text-base"
            />
          </div>
        </div>
        <Button disabled={!canGenerate} onClick={() => generate.mutate()}>
          {generate.isPending ? (
            <Loader2 className="animate-spin" />
          ) : (
            <Sparkles />
          )}
          {generate.isPending
            ? t({ zh: "生成中…", en: "Generating…" })
            : t(TERMS.aiGenerateDrafts)}
        </Button>

        {drafts !== null && (
          <div className="space-y-3 rounded-2xl border p-4">
            <p className="text-xs text-muted-foreground">
              {t({
                zh: `共 ${drafts.length} 条草稿（另有 ${dropped} 条被格式/重复检查丢弃）。目标词库：${bookTitle ?? "未选择"}`,
                en: `${drafts.length} drafts (${dropped} dropped by checks). Target book: ${bookTitle ?? "none selected"}`,
              })}
              {generatedAt &&
                ` · ${t({ zh: "生成时间", en: "Generated" })} ${formatDateTime(generatedAt, lang)}`}
            </p>
            <ul className="space-y-2">
              {drafts.map((row, index) => (
                <li
                  key={`${row.headword}-${index}`}
                  className="grid items-center gap-2 rounded-xl border p-2 lg:grid-cols-[auto_1fr_1fr_1fr_auto]"
                >
                  <label className="flex min-h-11 items-center gap-2 px-1 text-sm">
                    <input
                      type="checkbox"
                      checked={row.include}
                      onChange={(event) =>
                        updateRow(index, { include: event.target.checked })
                      }
                      className="size-4 accent-[var(--primary)]"
                      aria-label={t({
                        zh: "加入这条",
                        en: "Include this entry",
                      })}
                    />
                  </label>
                  <Input
                    value={row.headword}
                    onChange={(event) =>
                      updateRow(index, { headword: event.target.value })
                    }
                    aria-label={t({ zh: "单词", en: "Word" })}
                    className="h-10 text-base font-semibold"
                  />
                  <Input
                    value={row.part_of_speech}
                    onChange={(event) =>
                      updateRow(index, { part_of_speech: event.target.value })
                    }
                    placeholder={t({ zh: "词性", en: "pos" })}
                    aria-label={t({ zh: "词性", en: "Part of speech" })}
                    className="h-10 text-base"
                  />
                  <Input
                    value={row.meaning_zh}
                    onChange={(event) =>
                      updateRow(index, { meaning_zh: event.target.value })
                    }
                    placeholder={t({
                      zh: "中文释义（必填）",
                      en: "Chinese meaning (required)",
                    })}
                    aria-label={t({ zh: "中文释义", en: "Chinese meaning" })}
                    className="h-10 text-base"
                  />
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={t({ zh: "丢弃这条", en: "Drop this entry" })}
                    onClick={() =>
                      setDrafts((prev) =>
                        (prev ?? []).filter((_, i) => i !== index),
                      )
                    }
                  >
                    <Trash2 />
                  </Button>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                disabled={!canImport}
                onClick={() => importDrafts.mutate(included)}
              >
                {importDrafts.isPending && <Loader2 className="animate-spin" />}
                {t(
                  bookId
                    ? {
                        zh: `确认加入「${bookTitle ?? ""}」（${included.length} 条）`,
                        en: `Confirm into "${bookTitle ?? ""}" (${included.length})`,
                      }
                    : {
                        zh: "先在上方选择词库",
                        en: "Select a book above first",
                      },
                )}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setDrafts(null)}>
                {t({ zh: "放弃草稿", en: "Discard drafts" })}
              </Button>
              <p className="text-xs text-muted-foreground">
                {t(EXPLAIN_AI_CONTENT)}
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
