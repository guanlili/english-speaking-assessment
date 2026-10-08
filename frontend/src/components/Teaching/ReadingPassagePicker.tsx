import { ChevronDown, ChevronRight } from "lucide-react"
import { useState } from "react"
import type { PassageWithSentences } from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { useI18n } from "@/lib/i18n"
import { ReadingSentences } from "./ReadingSentences"

export function ReadingPassagePicker({
  passage,
  checked,
  onCheckedChange,
}: {
  passage: PassageWithSentences
  checked: boolean
  onCheckedChange: () => void
}) {
  const { t } = useI18n()
  const [expanded, setExpanded] = useState(false)
  const segments = passage.reading_segments ?? []
  return (
    <div
      className={`min-w-0 rounded-lg border ${checked ? "border-primary/50 bg-primary/5" : ""}`}
      data-testid={`pick-article-${passage.id}`}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2 p-3">
        <label
          htmlFor={`pick-passage-${passage.id}`}
          className="flex min-h-11 min-w-0 flex-1 cursor-pointer items-center gap-3"
        >
          <Checkbox
            id={`pick-passage-${passage.id}`}
            checked={checked}
            disabled={passage.is_active === false}
            onCheckedChange={onCheckedChange}
          />
          <span className="min-w-0">
            <span className="block break-words text-sm font-medium [overflow-wrap:anywhere]">
              {passage.title}
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {t({
                zh: `${passage.topic} · 建议 ${passage.suggested_seconds} 秒 · ${
                  segments.length > 0 ? `逐句 ${segments.length} 题` : "1 道题"
                }`,
                en: `${passage.topic} · suggested ${passage.suggested_seconds}s · ${
                  segments.length > 0
                    ? `${segments.length} sentence questions`
                    : "1 question"
                }`,
              })}
              {passage.is_active === false &&
                t({ zh: " · 已停用", en: " · Disabled" })}
            </span>
          </span>
        </label>
        <Button
          variant="ghost"
          className="min-h-11 shrink-0"
          aria-expanded={expanded}
          aria-controls={`pick-article-content-${passage.id}`}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? (
            <ChevronDown className="size-4" />
          ) : (
            <ChevronRight className="size-4" />
          )}
          {expanded
            ? t({ zh: "收起", en: "Collapse" })
            : t({ zh: "查看内容", en: "View content" })}
        </Button>
      </div>
      {expanded && (
        <div id={`pick-article-content-${passage.id}`} className="border-t p-3">
          {segments.length > 0 ? (
            <ReadingSentences segments={segments} />
          ) : (
            <p className="whitespace-pre-wrap break-words text-sm [overflow-wrap:anywhere]">
              {passage.text}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
