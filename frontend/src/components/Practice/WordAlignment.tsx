import { useI18n } from "@/lib/i18n"

/**
 * 跟读/复述逐词标注：把词级对齐结果渲染在参考原文上。
 *
 * - correct：正常显示
 * - missing：红底 + 删除线（漏读）
 * - error：黄底 + 波浪下划线，悬停显示听到的形式（读错）
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

  // 按偏移把原文切成「间隔文本 + 词」，保证标点/空格位置原样
  const segments: { plain?: string; word?: AlignedWordView }[] = []
  let cursor = 0
  for (const word of words) {
    if (word.start > cursor) {
      segments.push({ plain: reference.slice(cursor, word.start) })
    }
    segments.push({ word })
    cursor = Math.max(cursor, word.end)
  }
  if (cursor < reference.length) {
    segments.push({ plain: reference.slice(cursor) })
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
                  ? "rounded-sm bg-red-100 px-0.5 text-red-700 line-through decoration-red-400"
                  : segment.word.status === "error"
                    ? "cursor-help rounded-sm bg-amber-100 px-0.5 text-amber-800 underline decoration-amber-400 decoration-wavy"
                    : undefined
              }
              title={
                segment.word.status === "error" && segment.word.heard
                  ? t({
                      zh: `听到：${segment.word.heard}`,
                      en: `Heard: ${segment.word.heard}`,
                    })
                  : segment.word.status === "missing"
                    ? t({ zh: "漏读", en: "Missed" })
                    : undefined
              }
            >
              {segment.word.text}
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
      <p className="text-muted-foreground">
        <span className="mr-1">{t({ zh: "图例：", en: "Legend:" })}</span>
        <span className="rounded-sm bg-red-100 px-0.5 text-red-700 line-through">
          {t({ zh: "漏读", en: "missed" })}
        </span>
        <span className="mx-1 rounded-sm bg-amber-100 px-0.5 text-amber-800 underline decoration-amber-400 decoration-wavy">
          {t({ zh: "读错", en: "misread" })}
        </span>
      </p>
    </div>
  )
}

export default WordAlignment
