/**
 * 词汇分析块：展示用词来源级别（五级词库，唯一现行口径）。
 *
 * 历史分支：2026-10 前的作答携带老词表 A2/B1/B2 口径（wordlist/hits/
 * coverage/cefr），仅对历史作答保留展示并标注「老词表已退役」；不回填
 * 不重算。新作答只产出 level_stats（不代表能力等级）。
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
          zh: "词汇：分级词库未导入，暂无用词统计",
          en: "Vocabulary: leveled word source not imported — no stats yet",
        })}
      </div>
    )
  }

  const hasWordlist = Boolean(data.wordlist)

  const hits = data.hits ?? {}
  const hitWords = Array.from(new Set(Object.values(hits).flat())).slice(0, 24)

  const historical = hasWordlist // 老词表口径仅历史作答携带

  return (
    <div className="space-y-2 rounded-md border px-3 py-2">
      {historical && (
        <p className="text-xs text-amber-600">
          {t({
            zh: "老词表（A2/B1/B2）口径已退役——以下为历史作答的保留展示。",
            en: "The old A2/B1/B2 wordlist is retired — this is a preserved historical view.",
          })}
        </p>
      )}
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
      {historical && (
        <p className="text-xs text-muted-foreground">
          {t({
            zh: `词表来源：${data.wordlist}（已退役，仅历史展示）`,
            en: `Wordlist: ${data.wordlist} (retired, historical only)`,
          })}
        </p>
      )}
    </div>
  )
}

export default VocabBlock
