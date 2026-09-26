import { Badge } from "@/components/ui/badge"

/**
 * 词汇分析块（PRD US-07）：命中分级词、覆盖率、CEFR 参考标签。
 * vocab 为 null 时显示「未配置词表」，绝不编造等级（BDD D）。
 */

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
  const data = parseVocab(vocab)

  if (data === null) {
    return (
      <div className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
        词汇：未配置词表
      </div>
    )
  }

  const hits = data.hits ?? {}
  const bands = Object.keys(hits).sort()

  return (
    <div className="space-y-2 rounded-md border px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">词汇参考等级</span>
        <Badge variant="secondary">{data.cefr ?? "–"}</Badge>
        {typeof data.coverage === "number" && (
          <span className="text-xs text-muted-foreground">
            词表覆盖率 {Math.round(data.coverage * 100)}%
          </span>
        )}
      </div>
      {bands.length > 0 && (
        <div className="space-y-1 text-sm">
          {bands.map((band) => (
            <p key={band}>
              <span className="mr-1 text-muted-foreground">{band}：</span>
              {hits[band]?.slice(0, 12).join(", ")}
              {(hits[band]?.length ?? 0) > 12 && " …"}
            </p>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        词表来源：{data.wordlist ?? "未命名"} · 参考等级，不是官方 CEFR 证书
      </p>
    </div>
  )
}

export default VocabBlock
