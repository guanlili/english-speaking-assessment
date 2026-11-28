import { createFileRoute } from "@tanstack/react-router"

import { CourseEntitlements } from "@/components/Teaching/CourseEntitlements"
import { TeachingPageHeader } from "@/components/Teaching/TeachingPageHeader"
import { APP_NAME } from "@/config"
import { useI18n } from "@/lib/i18n"

export const Route = createFileRoute("/_layout/admin/courses")({
  component: CoursesPage,
  head: () => ({
    meta: [{ title: `课程与授权 / Courses & Licences - ${APP_NAME}` }],
  }),
})

function CoursesPage() {
  const { t } = useI18n()
  return (
    <div className="space-y-6">
      <TeachingPageHeader
        eyebrow={t({ zh: "校内管理", en: "School Settings" })}
        title={t({ zh: "课程与授权", en: "Courses & Licences" })}
        description={t({
          zh: "按课程查看本校的开通状态、授权方式与到期时间，并从这里进入各课程的内容管理。",
          en: "Review each course's status, grant and expiry, then jump into that course's content management.",
        })}
      />
      <CourseEntitlements />
    </div>
  )
}
