import { useMutation } from "@tanstack/react-query"
import { Loader2, RefreshCw } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import type {
  VocabularyAiOverallInsight,
  VocabularyAiSessionInsight,
  VocabularyAiWeakWord,
  VocabularyAiWordExplanation,
} from "@/client"
import { ApiError, VocabularyAiService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN_AI_CONTENT, EXPLAIN_AI_SCOPE, TERMS } from "@/lib/terms"
import { formatDate, formatDateTime } from "@/lib/time"

/** AI 触发的通用错误提示（503/429/422 都有后端双语 detail，前端兜底映射） */
export function aiErrorToast(
  error: unknown,
  t: (v: { zh: string; en: string }) => string,
) {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      toast.error(
        t({
          zh: "AI 生成次数已达上限，请稍后再试。",
          en: "AI generation limit reached — please retry later.",
        }),
      )
      return
    }
    if (error.status === 422) {
      toast.error(
        t({
          zh: "暂时不能生成：请检查条件（如答案尚未公布）。",
          en: "Can't generate right now — check the conditions (e.g. answers not published).",
        }),
      )
      return
    }
  }
  toast.error(
    t({
      zh: "AI 生成暂时不可用，练习与成绩不受影响。",
      en: "AI generation is unavailable right now — practice and scores are unaffected.",
    }),
  )
}

/** 单词结构化讲解对话框（按需生成，缓存由服务端管理） */
export function WordExplanationDialog({
  code,
  headword,
  meaningZh,
  partOfSpeech,
  open,
  onClose,
}: {
  code: string
  headword: string
  meaningZh: string
  partOfSpeech?: string | null
  open: boolean
  onClose: () => void
}) {
  const { t, lang } = useI18n()
  const [data, setData] = useState<VocabularyAiWordExplanation | null>(null)
  const [error, setError] = useState(false)
  const [pending, setPending] = useState(false)

  useEffect(() => {
    if (!open) return
    setPending(true)
    setError(false)
    VocabularyAiService.wordExplanation({
      code: code.toUpperCase(),
      requestBody: {
        headword,
        meaning_zh: meaningZh,
        part_of_speech: partOfSpeech ?? undefined,
      },
    })
      .then((result: VocabularyAiWordExplanation) => setData(result))
      .catch((err: unknown) => {
        aiErrorToast(err, t)
        setError(true)
      })
      .finally(() => setPending(false))
  }, [open, code, headword, meaningZh, partOfSpeech, t])

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {t(TERMS.aiWordExplanation)} · {headword}
          </DialogTitle>
          <DialogDescription>{t(EXPLAIN_AI_CONTENT)}</DialogDescription>
        </DialogHeader>
        {pending ? (
          <div
            role="status"
            className="flex items-center gap-2 py-6 text-sm text-muted-foreground"
          >
            <Loader2 className="size-4 animate-spin" />
            {t({ zh: "正在生成讲解…", en: "Generating explanation…" })}
          </div>
        ) : error || !data ? (
          <p role="alert" className="py-6 text-sm text-muted-foreground">
            {t({
              zh: "讲解没有生成成功，可稍后重试。",
              en: "Explanation failed — retry later.",
            })}
          </p>
        ) : (
          <div className="space-y-4">
            <section>
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                {t({ zh: "词义", en: "Meanings" })}
              </p>
              <ul className="list-inside list-disc space-y-0.5 text-sm">
                {(data.meanings ?? []).map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </section>
            {(data.common_misspellings ?? []).length > 0 && (
              <section>
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  {t({ zh: "常见误拼", en: "Common misspellings" })}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {(data.common_misspellings ?? []).map((m) => (
                    <span
                      key={m}
                      className="rounded-lg bg-secondary px-2 py-0.5 font-mono text-xs line-through"
                    >
                      {m}
                    </span>
                  ))}
                </div>
              </section>
            )}
            {(data.memory_tips ?? []).length > 0 && (
              <section>
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  {t({ zh: "记忆提示", en: "Memory tips" })}
                </p>
                <ul className="list-inside list-disc space-y-0.5 text-sm">
                  {(data.memory_tips ?? []).map((tip) => (
                    <li key={tip}>{tip}</li>
                  ))}
                </ul>
              </section>
            )}
            {(data.examples ?? []).length > 0 && (
              <section>
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  {t({ zh: "例句", en: "Examples" })}
                </p>
                <ul className="space-y-0.5 text-sm italic">
                  {(data.examples ?? []).map((example) => (
                    <li key={example}>{example}</li>
                  ))}
                </ul>
              </section>
            )}
            <p className="text-[11px] text-muted-foreground">
              {t({ zh: "生成时间", en: "Generated" })}{" "}
              {formatDateTime(data.generated_at, lang)}
              {data.cached && ` · ${t({ zh: "缓存结果", en: "cached" })}`}
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** 学情正文：总结 + 有证据的薄弱词 + 可执行建议 */
function InsightBody({
  summary,
  weakWords,
  suggestions,
  scopeLines,
  generatedAt,
  cached,
  stale,
  onRegenerate,
  regenerating,
}: {
  summary: string
  weakWords: VocabularyAiWeakWord[]
  suggestions: string[]
  scopeLines: string[]
  generatedAt: string
  cached: boolean
  stale: boolean
  onRegenerate?: () => void
  regenerating?: boolean
}) {
  const { t, lang } = useI18n()
  return (
    <div className="space-y-4">
      {stale && (
        <p className="rounded-xl bg-amber-500/10 p-3 text-sm text-amber-600">
          {t({
            zh: "生成后有新的作答记录，以下内容可能不是最新，可重新生成。",
            en: "New answers arrived after this was generated — regenerate for the latest.",
          })}
        </p>
      )}
      <p className="rounded-2xl bg-secondary/50 p-4 text-sm leading-6">
        {summary}
      </p>
      {weakWords.length > 0 && (
        <section>
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">
            {t({
              zh: "薄弱词（有作答证据）",
              en: "Weak words (with evidence)",
            })}
          </p>
          <ul className="space-y-1.5">
            {weakWords.map((word) => (
              <li
                key={word.headword + word.your_answer}
                className="flex flex-wrap items-baseline gap-x-2 rounded-xl border px-3 py-2 text-sm"
              >
                <span className="font-semibold">{word.headword}</span>
                <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                  {word.meaning_zh}
                </span>
                <span className="font-mono text-xs text-muted-foreground line-through">
                  {word.your_answer}
                </span>
                <span className="font-mono text-xs font-semibold">
                  {word.correct_spelling}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {suggestions.length > 0 && (
        <section>
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">
            {t({ zh: "复习建议", en: "Suggestions" })}
          </p>
          <ul className="list-inside list-disc space-y-1 text-sm">
            {suggestions.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </section>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <span>
          {scopeLines.join(" · ")}
          {" · "}
          {t({ zh: "生成时间", en: "Generated" })}{" "}
          {formatDateTime(generatedAt, lang)}
          {cached && !stale && ` · ${t({ zh: "缓存结果", en: "cached" })}`}
        </span>
        {onRegenerate && (
          <Button
            size="sm"
            variant="ghost"
            disabled={regenerating}
            onClick={onRegenerate}
          >
            <RefreshCw className={regenerating ? "animate-spin" : ""} />
            {t(TERMS.aiRegenerate)}
          </Button>
        )}
      </div>
    </div>
  )
}

/** 单次学情对话框（只读本轮真实作答） */
export function SessionInsightDialog({
  code,
  sessionId,
  open,
  onClose,
}: {
  code: string
  sessionId: string | null
  open: boolean
  onClose: () => void
}) {
  const { t } = useI18n()
  const [data, setData] = useState<VocabularyAiSessionInsight | null>(null)

  const generate = useMutation({
    mutationFn: (opts: { force: boolean }) =>
      VocabularyAiService.sessionInsight({
        code: code.toUpperCase(),
        requestBody: { session_id: sessionId as string, force: opts.force },
      }),
    onSuccess: (result) => setData(result as VocabularyAiSessionInsight),
    onError: (err) => aiErrorToast(err, t),
  })

  useEffect(() => {
    if (open && sessionId) {
      setData(null)
      generate.mutate({ force: false })
    }
  }, [open, sessionId, generate.mutate])

  const regenerating = generate.isPending

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t(TERMS.aiSessionInsight)}</DialogTitle>
          <DialogDescription>{t(EXPLAIN_AI_SCOPE)}</DialogDescription>
        </DialogHeader>
        {generate.isPending ? (
          <div
            role="status"
            className="flex items-center gap-2 py-6 text-sm text-muted-foreground"
          >
            <Loader2 className="size-4 animate-spin" />
            {t({ zh: "正在分析本轮作答…", en: "Analyzing this round…" })}
          </div>
        ) : generate.isError || !data ? (
          <p role="alert" className="py-6 text-sm text-muted-foreground">
            {t({
              zh: "分析没有生成成功，可稍后重试。",
              en: "Analysis failed — retry later.",
            })}
          </p>
        ) : (
          <InsightBody
            summary={data.summary}
            weakWords={data.weak_words ?? []}
            suggestions={data.suggestions ?? []}
            scopeLines={[
              t({
                zh: `本轮已答 ${data.scope?.answered_count ?? 0}/${data.scope?.total_count ?? 0} 题`,
                en: `${data.scope?.answered_count ?? 0}/${data.scope?.total_count ?? 0} answered`,
              }),
            ]}
            generatedAt={data.generated_at}
            cached={data.cached ?? false}
            stale={data.stale ?? false}
            regenerating={regenerating}
            onRegenerate={() => generate.mutate({ force: true })}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

/** 整体学习建议对话框（最近 N 轮 × M 天） */
export function OverallInsightDialog({
  code,
  open,
  onClose,
}: {
  code: string
  open: boolean
  onClose: () => void
}) {
  const { t, lang } = useI18n()
  const [data, setData] = useState<VocabularyAiOverallInsight | null>(null)

  const generate = useMutation({
    mutationFn: (opts: { force: boolean }) =>
      VocabularyAiService.overallInsight({
        code: code.toUpperCase(),
        requestBody: { limit: 10, days: 30, force: opts.force },
      }),
    onSuccess: (result) => setData(result as VocabularyAiOverallInsight),
    onError: (err) => aiErrorToast(err, t),
  })

  useEffect(() => {
    if (open) {
      setData(null)
      generate.mutate({ force: false })
    }
  }, [open, generate.mutate])

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t(TERMS.aiOverallInsight)}</DialogTitle>
          <DialogDescription>{t(EXPLAIN_AI_SCOPE)}</DialogDescription>
        </DialogHeader>
        {generate.isPending ? (
          <div
            role="status"
            className="flex items-center gap-2 py-6 text-sm text-muted-foreground"
          >
            <Loader2 className="size-4 animate-spin" />
            {t({ zh: "正在分析最近练习…", en: "Analyzing recent practice…" })}
          </div>
        ) : generate.isError || !data ? (
          <p role="alert" className="py-6 text-sm text-muted-foreground">
            {t({
              zh: "分析没有生成成功：范围内可能还没有练习记录。",
              en: "Analysis failed — there may be no practice records in range.",
            })}
          </p>
        ) : (
          <InsightBody
            summary={data.summary}
            weakWords={data.weak_words ?? []}
            suggestions={data.suggestions ?? []}
            scopeLines={[
              t({
                zh: `最近 ${data.scope?.rounds ?? 0} 轮 · ${data.scope?.days ?? 0} 天内`,
                en: `last ${data.scope?.rounds ?? 0} rounds · ${data.scope?.days ?? 0} days`,
              }),
              t({
                zh: `作答 ${data.scope?.answered_count ?? 0} 题`,
                en: `${data.scope?.answered_count ?? 0} answers`,
              }),
              data.scope?.from_time
                ? `${formatDate(data.scope.from_time, lang)} ~ ${formatDate(data.scope.to_time ?? "", lang)}`
                : "",
            ].filter(Boolean)}
            generatedAt={data.generated_at}
            cached={data.cached ?? false}
            stale={data.stale ?? false}
            regenerating={generate.isPending}
            onRegenerate={() => generate.mutate({ force: true })}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
