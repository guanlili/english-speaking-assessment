import { useI18n } from "@/lib/i18n"

/** 分句是文章题的子内容，不能单独勾选或作为听句复述发布。 */
export function ReadingSentences({ segments }: { segments: string[] }) {
  const { t } = useI18n()
  if (segments.length === 0) return null
  return (
    <div className="space-y-2" data-testid="reading-sentences">
      <p className="text-sm font-medium">
        {t({
          zh: `朗读分句 · ${segments.length} 句`,
          en: `Reading sentences · ${segments.length}`,
        })}
      </p>
      <p className="text-xs text-muted-foreground">
        {t({
          zh: "句子是文章的组成内容，组卷时选择整篇文章。",
          en: "Sentences belong to this article. Select the whole article when composing a practice.",
        })}
      </p>
      <ol className="ml-2 space-y-2 border-l-2 pl-3 sm:ml-4 sm:pl-4">
        {segments.map((text, index) => (
          <li
            key={`${index}-${text}`}
            className="flex min-w-0 gap-3 rounded-lg border bg-card p-3 text-sm"
          >
            <span className="shrink-0 text-muted-foreground">{index + 1}.</span>
            <p className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
              {text}
            </p>
          </li>
        ))}
      </ol>
    </div>
  )
}
