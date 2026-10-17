import { Lock } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/lib/i18n"

export function ReadOnlyContentBadge() {
  const { t } = useI18n()
  return (
    <Badge variant="secondary" className="gap-1" data-testid="readonly-content">
      <Lock className="size-3" />
      {t({
        zh: "校内共享 · 原作者可编辑",
        en: "School library · author can edit",
      })}
    </Badge>
  )
}
