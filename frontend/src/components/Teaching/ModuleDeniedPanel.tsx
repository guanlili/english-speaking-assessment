import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import type { ModuleKey } from "@/hooks/useModules"
import { useI18n } from "@/lib/i18n"

const COPY: Record<ModuleKey, { zh: string; en: string }> = {
  speaking: {
    zh: "本校暂未开通口语模块。",
    en: "The speaking module is not enabled for this school.",
  },
  vocabulary: {
    zh: "本校暂未开通词汇模块。",
    en: "The vocabulary module is not enabled for this school.",
  },
}

/**
 * 模块未购拦截页：直连未购模块入口时展示，附回课堂列表入口。
 * 服务端闸门仍是最终裁决，前端拦截只减少无效直达。
 */
export function ModuleDeniedPanel({ module }: { module: ModuleKey }) {
  const { t } = useI18n()
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-muted-foreground">
      {t(COPY[module])}
      <Button variant="outline" asChild>
        <Link to="/classrooms">
          {t({ zh: "回课堂列表", en: "Back to Classes" })}
        </Link>
      </Button>
    </div>
  )
}
