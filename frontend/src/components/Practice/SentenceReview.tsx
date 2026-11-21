import { CheckCircle2, Loader2, TriangleAlert } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/lib/i18n"
import { sliceByCodepoints } from "@/lib/word-alignment"

interface ReviewIssue {
  type: "grammar" | "expression"
  start: number
  end: number
  span: string
  suggestion: string
  why: { zh: string; en: string }
}

interface ReviewSentence {
  index: number
  text: string
  start: number
  end: number
  clean: boolean
  corrected: string
  issues: ReviewIssue[]
}

interface ReviewPayload {
  status: "pending" | "done" | "unavailable" | string
  truncated?: boolean
  sentences: ReviewSentence[]
  summary?: { zh?: string; en?: string }
}

function parseIssue(raw: unknown): ReviewIssue | null {
  if (!raw || typeof raw !== "object") return null
  const value = raw as Record<string, unknown>
  if (value.type !== "grammar" && value.type !== "expression") return null
  if (typeof value.start !== "number" || typeof value.end !== "number") {
    return null
  }
  if (typeof value.span !== "string" || typeof value.suggestion !== "string") {
    return null
  }
  const why =
    value.why && typeof value.why === "object"
      ? (value.why as Record<string, unknown>)
      : {}
  return {
    type: value.type,
    start: value.start,
    end: value.end,
    span: value.span,
    suggestion: value.suggestion,
    why: {
      zh: typeof why.zh === "string" ? why.zh : "",
      en: typeof why.en === "string" ? why.en : "",
    },
  }
}

function parseReview(raw: unknown): ReviewPayload | null {
  if (!raw || typeof raw !== "object") return null
  const value = raw as Record<string, unknown>
  const status = typeof value.status === "string" ? value.status : ""
  const rawSentences = Array.isArray(value.sentences) ? value.sentences : []
  const sentences: ReviewSentence[] = []
  for (const item of rawSentences) {
    if (!item || typeof item !== "object") continue
    const sentence = item as Record<string, unknown>
    if (
      typeof sentence.text !== "string" ||
      typeof sentence.start !== "number" ||
      typeof sentence.end !== "number"
    ) {
      continue
    }
    const issues = Array.isArray(sentence.issues)
      ? sentence.issues
          .map(parseIssue)
          .filter((issue): issue is ReviewIssue => issue !== null)
      : []
    sentences.push({
      index:
        typeof sentence.index === "number" ? sentence.index : sentences.length,
      text: sentence.text,
      start: sentence.start,
      end: sentence.end,
      clean: issues.length === 0,
      corrected:
        typeof sentence.corrected === "string"
          ? sentence.corrected
          : sentence.text,
      issues,
    })
  }
  const summary =
    value.summary && typeof value.summary === "object"
      ? (value.summary as Record<string, unknown>)
      : {}
  return {
    status,
    truncated: value.truncated === true,
    sentences,
    summary: {
      zh: typeof summary.zh === "string" ? summary.zh : "",
      en: typeof summary.en === "string" ? summary.en : "",
    },
  }
}

function issueClassName(type: ReviewIssue["type"]): string {
  return type === "grammar"
    ? "rounded-sm underline decoration-red-500 decoration-wavy decoration-2 underline-offset-4"
    : "rounded-sm underline decoration-amber-500 decoration-2 underline-offset-4"
}

function SentenceText({ sentence }: { sentence: ReviewSentence }) {
  const total = Array.from(sentence.text).length
  const valid = sentence.issues
    .filter(
      (issue) =>
        issue.start >= 0 && issue.end <= total && issue.end > issue.start,
    )
    .sort((a, b) => a.start - b.start)
  const segments: { plain?: string; issue?: ReviewIssue }[] = []
  let cursor = 0
  for (const issue of valid) {
    if (issue.start > cursor) {
      segments.push({
        plain: sliceByCodepoints(sentence.text, cursor, issue.start),
      })
    }
    segments.push({ issue })
    cursor = Math.max(cursor, issue.end)
  }
  if (cursor < total) {
    segments.push({ plain: sliceByCodepoints(sentence.text, cursor) })
  }
  if (segments.length === 0) return <>{sentence.text}</>
  return (
    <>
      {segments.map((segment, index) =>
        segment.issue ? (
          <span
            key={`${segment.issue.start}-${index}`}
            className={issueClassName(segment.issue.type)}
            title={segment.issue.span}
          >
            {sliceByCodepoints(
              sentence.text,
              segment.issue.start,
              segment.issue.end,
            )}
          </span>
        ) : (
          <span key={`plain-${index}`}>{segment.plain}</span>
        ),
      )}
    </>
  )
}

/** 问答逐句批改卡片：语法/表达问题 + 最小改写；发音区 P0 只显示占位。 */
export function SentenceReview({ review }: { review: unknown }) {
  const { t, lang } = useI18n()
  const data = parseReview(review)
  if (data === null) return null

  if (data.status === "pending") {
    return (
      <div className="flex items-center gap-2 rounded-xl border bg-muted/30 p-3 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        {t({
          zh: "逐句批改正在生成…",
          en: "Sentence review is being generated…",
        })}
      </div>
    )
  }

  if (data.status === "unavailable" || data.sentences.length === 0) {
    return (
      <div className="flex items-start gap-2 rounded-xl border border-dashed p-3 text-sm text-muted-foreground">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" />
        {t({
          zh: "本次逐句批改暂缺（语法/表达）；参考分与四维评价不受影响。",
          en: "Sentence review is unavailable this time (grammar/expression). Your score and rubric are unaffected.",
        })}
      </div>
    )
  }

  const issueCount = data.sentences.reduce(
    (sum, sentence) => sum + sentence.issues.length,
    0,
  )
  const grammarCount = data.sentences.reduce(
    (sum, sentence) =>
      sum + sentence.issues.filter((issue) => issue.type === "grammar").length,
    0,
  )
  const expressionCount = issueCount - grammarCount
  const summary =
    lang === "zh" ? data.summary?.zh || "" : data.summary?.en || ""

  return (
    <section className="space-y-3 rounded-xl border bg-muted/20 p-3">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">
          {t({ zh: "逐句批改", en: "Sentence review" })}
        </h3>
        <span className="text-xs text-muted-foreground">
          {summary ||
            t({
              zh: `共 ${data.sentences.length} 句 · ${grammarCount} 处语法 · ${expressionCount} 处表达`,
              en: `${data.sentences.length} sentences · ${grammarCount} grammar · ${expressionCount} expression`,
            })}
        </span>
      </header>

      {data.truncated && (
        <p className="text-xs text-muted-foreground">
          {t({
            zh: "本次只批改前 12 句，其余句子未纳入。",
            en: "Only the first 12 sentences were reviewed.",
          })}
        </p>
      )}

      <ol className="space-y-3">
        {data.sentences.map((sentence) => (
          <li key={`${sentence.index}-${sentence.start}`} className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>
                {t({
                  zh: `第 ${sentence.index + 1} 句`,
                  en: `Sentence ${sentence.index + 1}`,
                })}
              </span>
              {sentence.clean ? (
                <span className="flex items-center gap-1 text-emerald-700">
                  <CheckCircle2 className="size-3.5" />
                  {t({ zh: "这句没问题", en: "No issue" })}
                </span>
              ) : (
                <Badge variant="outline" className="text-red-700">
                  {t({
                    zh: `${sentence.issues.length} 处问题`,
                    en: `${sentence.issues.length} issue(s)`,
                  })}
                </Badge>
              )}
            </div>
            <p className="text-sm leading-relaxed">
              <SentenceText sentence={sentence} />
            </p>

            {!sentence.clean && (
              <div className="space-y-1.5">
                {sentence.corrected && sentence.corrected !== sentence.text && (
                  <p className="rounded-lg bg-background px-2.5 py-1.5 text-sm">
                    <span className="text-muted-foreground">
                      {t({ zh: "建议改为：", en: "Suggested: " })}
                    </span>
                    {sentence.corrected}
                  </p>
                )}
                <ul className="space-y-1">
                  {sentence.issues.map((issue, index) => {
                    const why = lang === "zh" ? issue.why.zh : issue.why.en
                    return (
                      <li
                        key={`${issue.start}-${issue.type}-${index}`}
                        className="flex flex-wrap items-start gap-1.5 text-xs leading-relaxed"
                      >
                        <Badge
                          variant="outline"
                          className={
                            issue.type === "grammar"
                              ? "text-red-700"
                              : "text-amber-700"
                          }
                        >
                          {issue.type === "grammar"
                            ? t({ zh: "语法", en: "Grammar" })
                            : t({ zh: "表达", en: "Expression" })}
                        </Badge>
                        <span className="font-medium">
                          {issue.span} → {issue.suggestion}
                        </span>
                        {why && (
                          <span className="text-muted-foreground">{why}</span>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}
          </li>
        ))}
      </ol>

      <p className="border-t pt-2 text-xs text-muted-foreground">
        {t({
          zh: "发音评测待接入；本期只批改语法与表达，不改现有参考分口径。",
          en: "Pronunciation assessment is not connected yet; this review covers grammar and expression only and does not change scores.",
        })}
      </p>
    </section>
  )
}

export default SentenceReview
