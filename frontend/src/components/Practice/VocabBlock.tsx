/**
 * 词汇分析块（PRD US-07）：展示命中的表达和词表覆盖率。
 * 档位仅作为后台词表元数据，不向学生展示，避免把练习反馈误解成能力等级。
 *
 * 2026-10 起追加「用词来源级别」（五级词库）：只陈述实际用到的词来自哪些
 * 级别（两模块共用的分级数据源），明确标注不代表能力等级；历史作答没有
 * level_stats 字段则不显示该块（不回填、不重算）。
 */

import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/lib/i18n"
import {
  TERMS,
  VOCAB_LEVEL_LABELS,
  VOCAB_LEVEL_ORDER,
  type VocabLevel,
} from "@/lib/terms"

interface VocabPayload {
  wordlist?: string
  hits?: Record<string, string[]>
  coverage?: number
  cefr?: string | null
  level_stats?: {
    hits_by_level?: Record<string, number>
    unmatched?: number
    distinct_words?: number
  } | null
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

  const hasWordlist = Boolean(data.wordlist)

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
      {/* 用词来源级别（五级词库；只陈述来源，不代表能力等级） */}
      {data.level_stats &&
        Object.values(data.level_stats.hits_by_level ?? {}).some(
          (n) => n > 0,
        ) && (
          <div className="space-y-1 border-t pt-2 text-sm">
            <p className="text-muted-foreground">{t(TERMS.wordSourceLevel)}</p>
            <div className="flex flex-wrap gap-1.5">
              {VOCAB_LEVEL_ORDER.map((level: VocabLevel) => {
                const count = data.level_stats?.hits_by_level?.[level] ?? 0
                if (count <= 0) return null
                return (
                  <Badge key={level} variant="secondary" className="text-xs">
                    {t(VOCAB_LEVEL_LABELS[level])} × {count}
                  </Badge>
                )
              })}
            </div>
            <p className="text-xs text-muted-foreground">
              {t(TERMS.wordSourceLevelNote)}
            </p>
          </div>
        )}
      {hasWordlist && (
        <p className="text-xs text-muted-foreground">
          {t({
            zh: `词表来源：${data.wordlist} · 仅用于发现可继续使用的表达`,
            en: `Wordlist: ${data.wordlist} · used only to spot expressions you can keep using`,
          })}
        </p>
      )}
    </div>
  )
}

export default VocabBlock
