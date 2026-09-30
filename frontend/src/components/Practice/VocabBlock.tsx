/**
 * 词汇分析块（PRD US-07）：展示命中的表达和词表覆盖率。
 * 档位仅作为后台词表元数据，不向学生展示，避免把练习反馈误解成能力等级。
 */
import { useI18n } from "@/lib/i18n"

interface VocabPayload {
  wordlist?: string
  hits?: Record<string, string[]>
  coverage?: number
  cefr?: string | null
}

function parseVocab(raw: unknown): VocabPayload | null {
  if (raw === null || raw === undefined) return null
  if (typeof raw !== "object") return null
  return raw as VocabPayload
}

function VocabBlock({ vocab }: { vocab: unknown }) {
  const { t } = useI18n()
  const data = parseVocab(vocab)

  if (data === null) {
    return (
      <div className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
        {t({
          zh: "词汇：未配置词表",
          en: "Vocabulary: no wordlist configured",
        })}
      </div>
    )
  }

  const hits = data.hits ?? {}
  const hitWords = Array.from(new Set(Object.values(hits).flat())).slice(0, 24)

  return (
    <div className="space-y-2 rounded-md border px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">
          {t({ zh: "词汇使用", en: "Vocabulary use" })}
        </span>
        {typeof data.coverage === "number" && (
          <span className="text-xs text-muted-foreground">
            {t({
              zh: `词表覆盖率 ${Math.round(data.coverage * 100)}%`,
              en: `Wordlist coverage ${Math.round(data.coverage * 100)}%`,
            })}
          </span>
        )}
      </div>
      {hitWords.length > 0 && (
        <div className="space-y-1 text-sm">
          <p>
            <span className="mr-1 text-muted-foreground">
              {t({ zh: "命中表达：", en: "Expressions hit:" })}
            </span>
            {hitWords.join(", ")}
          </p>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        {t({
          zh: `词表来源：${data.wordlist ?? "未命名"} · 仅用于发现可继续使用的表达`,
          en: `Wordlist: ${data.wordlist ?? "Unnamed"} · used only to spot expressions you can keep using`,
        })}
      </p>
    </div>
  )
}

export default VocabBlock
