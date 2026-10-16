import { useI18n } from "@/lib/i18n"
import { skippedSpans } from "@/lib/skipped-spans"

/** 跟读/复述：按顺序标出跳过的片段。空转写不显示。 */
export function SkippedSpans({
  reference,
  transcript,
  itemType,
}: {
  reference: string | null | undefined
  transcript: string | null | undefined
  itemType: string
}) {
  const { t } = useI18n()
  if (itemType === "question" || itemType === "instruction") return null
  const spans = skippedSpans(reference ?? "", transcript ?? "")
  if (spans.length === 0) return null
  return (
    <div className="space-y-1 text-sm">
      <p className="text-muted-foreground">
        {t({
          zh: "按朗读顺序跳过了这些片段。这不是发音评分。",
          en: "These stretches were skipped in reading order. This is not a pronunciation score.",
        })}
      </p>
      <ul className="list-disc space-y-1 pl-5">
        {spans.map((span) => (
          <li key={span} className="break-words">
            {span}
          </li>
        ))}
      </ul>
    </div>
  )
}
