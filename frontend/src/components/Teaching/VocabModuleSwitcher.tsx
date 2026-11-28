import { Link } from "@tanstack/react-router"
import { BookA, Mic } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useModules } from "@/hooks/useModules"
import { COURSES } from "@/lib/courses"
import { useI18n } from "@/lib/i18n"

/**
 * 课程工作台头部「口语课 / 单词课」切换。
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
        <Button variant="outline" size="sm" className="max-sm:h-11" asChild>
          <Link to="/t/$code" params={{ code }}>
            <Mic />
            {t(COURSES.speaking.name)}
          </Link>
        </Button>
      )}
      <Button size="sm" className="max-sm:h-11" aria-current="page">
        <BookA />
        {t(COURSES.vocabulary.name)}
      </Button>
    </div>
  )
}
