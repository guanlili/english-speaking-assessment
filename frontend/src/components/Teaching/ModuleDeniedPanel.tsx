import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import type { ModuleKey } from "@/hooks/useModules"
import { COURSES } from "@/lib/courses"
import { useI18n } from "@/lib/i18n"

/**
 * 课程未开通拦截页：直连未开通课程入口时展示，附回课堂列表入口。
 * 文案从课程注册表取（"口语课 / 单词课"，不再叫"模块"）；
 * 服务端闸门仍是最终裁决，前端拦截只减少无效直达。
 */
export function ModuleDeniedPanel({ module }: { module: ModuleKey }) {
  const { t } = useI18n()
  const course = COURSES[module]
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-muted-foreground">
      {t({
        zh: `本校暂未开通${course.name.zh}。`,
        en: `${course.name.en} is not enabled for this school.`,
      })}
      <span className="max-w-md text-center text-sm">{t(course.tagline)}</span>
      <Button variant="outline" asChild>
        <Link to="/classrooms">
          {t({ zh: "回课堂列表", en: "Back to Classes" })}
        </Link>
      </Button>
    </div>
  )
}
