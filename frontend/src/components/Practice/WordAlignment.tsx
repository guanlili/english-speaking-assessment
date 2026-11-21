import { useI18n } from "@/lib/i18n"
import { sliceByCodepoints } from "@/lib/word-alignment"

/**
 * 跟读/复述逐词标注 P0：在参考原文上做文本匹配着色。
 *
 * - correct：绿色实线下划线（文本匹配正确，不等同发音评分）
 * - missing：红色下划线 + 删除线（漏读）
 * - error：红色实线下划线，括号内显示听到的形式（读错）
 *
 * 只做展示，不做发音评分；旧作答（无 word_alignment）由调用方回退 SkippedSpans。
 */
export interface AlignedWordView {
  start: number
  end: number
  text: string
  status: "correct" | "missing" | "error"
  heard?: string | null
}

const GOOD = "underline decoration-emerald-500 decoration-2 underline-offset-4"
const BAD = "underline decoration-red-500 decoration-2 underline-offset-4"
const MISSING =
  "[text-decoration-line:underline_line-through] decoration-red-500 decoration-2 underline-offset-4 text-red-700"

export function WordAlignment({
  reference,
  alignment,
}: {
  reference: string
  alignment?: {
    words?: AlignedWordView[]
    extras?: { text?: string }[]
  } | null
}) {
  const { t } = useI18n()
  const words = alignment?.words
  if (!words || words.length === 0) return null

  // 按码点偏移把原文切成「间隔文本 + 词」，保证标点/空格位置原样
  const segments: { plain?: string; word?: AlignedWordView }[] = []
  let cursor = 0
  for (const word of words) {
    if (word.start > cursor) {
      segments.push({ plain: sliceByCodepoints(reference, cursor, word.start) })
    }
    segments.push({ word })
    cursor = Math.max(cursor, word.end)
  }
  if (cursor < Array.from(reference).length) {
    segments.push({ plain: sliceByCodepoints(reference, cursor) })
  }

  const extras = alignment?.extras?.filter((e) => e.text) ?? []

  return (
    <div className="space-y-1 text-sm">
      <p className="leading-relaxed">
        {segments.map((segment, index) =>
          segment.word ? (
            <span
              key={`${segment.word.start}-${index}`}
              className={
                segment.word.status === "missing"
                  ? MISSING
                  : segment.word.status === "error"
                    ? `cursor-help ${BAD}`
                    : GOOD
              }
              title={
                segment.word.status === "error" && segment.word.heard
                  ? t({
                      zh: `听到：${segment.word.heard}`,
                      en: `Heard: ${segment.word.heard}`,
                    })
                  : segment.word.status === "missing"
                    ? t({ zh: "漏读", en: "Missed" })
                    : t({
                        zh: "文本匹配正确（非发音评分）",
                        en: "Text match (not a pronunciation score)",
                      })
              }
            >
              {segment.word.text}
              {segment.word.status === "error" && segment.word.heard && (
                <span className="ml-0.5 text-xs font-normal text-red-900/80">
                  ({segment.word.heard})
                </span>
              )}
            </span>
          ) : (
            <span key={`plain-${index}`}>{segment.plain}</span>
          ),
        )}
      </p>
      {extras.length > 0 && (
        <p className="text-muted-foreground">
          <span className="mr-1">{t({ zh: "多读：", en: "Extra:" })}</span>
          {extras.map((extra, index) => (
            <span
              key={`${extra.text}-${index}`}
              className="mr-1 inline-block rounded-full bg-muted px-1.5 py-0.5 text-xs"
            >
              {extra.text}
            </span>
          ))}
        </p>
      )}
      <p className="text-xs leading-relaxed text-muted-foreground">
        <span className="mr-1">{t({ zh: "图例：", en: "Legend:" })}</span>
        <span className={`${GOOD} mx-0.5`}>
          {t({ zh: "文本匹配正确", en: "text match" })}
        </span>
        <span className={`${BAD} mx-0.5`}>
          {t({ zh: "读错", en: "misread" })}
        </span>
        <span className={`${MISSING} mx-0.5`}>
          {t({ zh: "漏读", en: "missed" })}
        </span>
      </p>
      <p className="text-xs text-muted-foreground">
        {t({
          zh: "当前为转写文本匹配，不代表发音评分；发音评测待接入。",
          en: "Based on transcript matching, not pronunciation scoring. Pronunciation assessment is not connected yet.",
        })}
      </p>
    </div>
  )
}

export default WordAlignment
