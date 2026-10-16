import { Lock } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/lib/i18n"

export function ReadOnlyContentBadge() {
  const { t } = useI18n()
  return (
    <Badge variant="secondary" className="gap-1" data-testid="readonly-content">
      <Lock className="size-3" />
      {t({ zh: "其他老师创建 · 只读", en: "Another teacher's · read-only" })}
    </Badge>
  )
}
