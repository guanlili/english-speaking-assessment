import type { PlanItem } from "@/client"
import { useI18n } from "@/lib/i18n"

/**
 * 题面文本区：说明页标题、正文（复述题不显示文字）、提示语/译文。
 * 「收起原文（练记忆）」的 hideText 状态由页面持有，跨题保持。
 */
export default function PromptTextBlock({
  item,
  isInstruction,
  hideText,
  inExam,
  hint,
}: {
  item: PlanItem
  isInstruction: boolean
  hideText: boolean
  inExam: boolean
  hint: string
}) {
  const { t } = useI18n()
  if (item.type === "repeat") {
    return (
      <p className="prompt-display min-h-24 text-muted-foreground">
        {t({
          zh: "本题不显示文字。点下方「听示范」听语音，听完后复述出来。",
          en: "No text for this item. Tap Listen below to hear it, then repeat what you heard.",
        })}
      </p>
    )
  }
  return (
    <>
      {isInstruction && item.title && (
        <p className="text-sm font-semibold text-foreground">{item.title}</p>
      )}
      <p
        className={`prompt-display min-h-24 whitespace-pre-wrap break-words [overflow-wrap:anywhere] ${inExam ? "select-none" : ""}`}
      >
        {hideText
          ? t({
              zh: "原文已收起。试着回想刚刚听到的内容。",
              en: "The text is hidden. Try to recall what you just heard.",
            })
          : item.text}
      </p>
      <p className="text-xs text-muted-foreground">
        {hideText
          ? t({
              zh: "想不起来也没关系，随时可以重新看看。",
              en: "It's fine if you can't remember — you can peek anytime.",
            })
          : isInstruction
            ? hint
            : (item.translation ?? hint)}
      </p>
    </>
  )
}

/** 复述题的附加提示行（题面下方）。 */
export function RepeatHint({ hint }: { hint: string }) {
  return <p className="text-xs text-muted-foreground">{hint}</p>
}
