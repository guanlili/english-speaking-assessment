import { CircleHelp } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

/**
 * 触点解释：小问号图标，hover / 聚焦显示说明，aria-label 供读屏与触屏使用。
 * 文案从 `@/lib/terms` 的 EXPLAIN 取，保证与帮助页口径一致。
 */
function InfoHint({
  label,
  side = "top",
}: {
  label: string
  side?: "top" | "bottom" | "left" | "right"
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className="inline-flex shrink-0 cursor-help rounded-sm text-muted-foreground/70 transition hover:text-foreground"
        >
          <CircleHelp className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent side={side} className="max-w-64 text-xs leading-relaxed">
        {label}
      </TooltipContent>
    </Tooltip>
  )
}

export default InfoHint
