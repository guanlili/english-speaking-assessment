import { Card, CardContent } from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"

export type RoundStats = {
  overall: number | null
  completeness: number | null
  fluency: number | null
  vocabCefr: string | null
  hitWords: string[]
  rubric?: {
    fluency?: number
    vocabulary?: number
    grammar?: number
    task?: number
    mock_score?: number
    count: number
  }
}

export function RoundStatsGrid({ roundStats }: { roundStats: RoundStats }) {
  const { t } = useI18n()
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {(
        [
          [
            t({ zh: "参考分", en: "Reference Score" }),
            roundStats.overall,
            t({ zh: "本轮均值", en: "Round average" }),
          ],
          [
            t({ zh: "完整度参考", en: "Completeness" }),
            roundStats.completeness,
            t(TERMS.typeRepeat),
          ],
          [
            t({ zh: "流利度参考", en: "Fluency" }),
            roundStats.fluency,
            t({ zh: "全部题目", en: "All items" }),
          ],
          [
            t({ zh: "词汇覆盖", en: "Vocabulary" }),
            roundStats.vocabCefr
              ? t({ zh: "已分析（历史口径）", en: "Analyzed (legacy)" })
              : "–",
            t({
              zh: "老词表口径仅历史作答保留；现行为五级词库口径",
              en: "Legacy wordlist kept for past answers; current standard is five-level",
            }),
          ],
        ] as const
      ).map(([label, value, note]) => (
        <Card key={label}>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="mt-1 text-2xl font-bold tabular-nums">
              {value === null ? "–" : value}
            </p>
            <p className="text-[10px] text-muted-foreground">{note}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
