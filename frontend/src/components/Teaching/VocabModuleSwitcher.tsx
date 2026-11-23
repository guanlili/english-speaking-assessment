import { Link } from "@tanstack/react-router"
import { BookA, Mic } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useModules } from "@/hooks/useModules"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"

/**
 * 词汇页头部「口语 / 词汇」切换。
 *
 * 口语入口仅在已购 speaking 时出现，与课堂面板头部的模块显隐同口径：
 * 模块清单统一走 `useModules`，服务端闸门仍是最终裁决，前端隐藏只减少无效直达。
 */
export function VocabModuleSwitcher({ code }: { code: string }) {
  const { t } = useI18n()
  const { hasModule } = useModules()

  return (
    <div className="flex gap-2">
      {hasModule("speaking") && (
        <Button variant="outline" size="sm" asChild>
          <Link to="/t/$code" params={{ code }}>
            <Mic />
            {t({ zh: "口语练习", en: "Speaking" })}
          </Link>
        </Button>
      )}
      <Button size="sm" aria-current="page">
        <BookA />
        {t(TERMS.vocabLearning)}
      </Button>
    </div>
  )
}
