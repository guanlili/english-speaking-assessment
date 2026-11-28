import { Link } from "@tanstack/react-router"
import { ArrowRight, BadgeCheck, BookA, Mic } from "lucide-react"

import { useModules } from "@/hooks/useModules"
import type { CourseKey } from "@/lib/courses"
import { COURSE_LIST } from "@/lib/courses"
import { useI18n } from "@/lib/i18n"
import { describeModuleBadge } from "@/lib/tenantModules"

/**
 * 校管「课程与授权」：把授权按课程包呈现，而不是按内部 module_key 呈现。
 *
 * 口径：
 * - 只读：开关与续期属于平台运营（学校管理员不可改），本页只展示状态与到期，
 *   并给出该课程下的内容管理入口；
 * - 状态徽标复用 `describeModuleBadge`，与顶部到期提醒横幅同一状态机，不另算；
 * - 课程清单来自 `COURSE_LIST`，将来登记阅读课等新课程会自动出现在本页。
 */
const COURSE_ICONS: Record<CourseKey, typeof Mic> = {
  speaking: Mic,
  vocabulary: BookA,
}

const COURSE_ADMIN_LINKS: Record<
  CourseKey,
  Array<{
    to: "/admin/units" | "/admin/sentenceframes" | "/admin/vocabbooks"
    label: { zh: string; en: string }
  }>
> = {
  speaking: [
    { to: "/admin/units", label: { zh: "单元管理", en: "Units" } },
    {
      to: "/admin/sentenceframes",
      label: { zh: "句型库", en: "Sentence Frames" },
    },
  ],
  vocabulary: [
    { to: "/admin/vocabbooks", label: { zh: "词库管理", en: "Word Books" } },
  ],
}

export function CourseEntitlements() {
  const { t } = useI18n()
  const { statusOf, hasModule, isPending, isError } = useModules()

  if (isPending) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {t({ zh: "正在加载授权状态…", en: "Loading entitlements…" })}
      </p>
    )
  }
  if (isError) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {t({
          zh: "授权状态暂时取不到，请稍后刷新重试。",
          en: "Entitlements are unavailable right now — please refresh later.",
        })}
      </p>
    )
  }

  return (
    <div className="space-y-4">
      {COURSE_LIST.map((course) => {
        const status = statusOf(course.key)
        const badge = describeModuleBadge(status)
        const Icon = COURSE_ICONS[course.key]
        const enabled = hasModule(course.key)
        return (
          <div
            key={course.key}
            className="rounded-2xl border border-border/60 bg-card p-5"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-3">
                <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-secondary text-primary">
                  <Icon className="size-4" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <h2 className="text-base font-semibold">{t(course.name)}</h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t(course.tagline)}
                  </p>
                </div>
              </div>
              <span className="inline-flex items-center gap-1 rounded-full border border-border/60 px-2.5 py-1 text-xs">
                <BadgeCheck
                  className={
                    enabled
                      ? "size-3.5 text-primary"
                      : "size-3.5 text-muted-foreground"
                  }
                  aria-hidden="true"
                />
                {t(badge.label)}
              </span>
            </div>

            <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground">
                  {t({ zh: "授权方式", en: "Grant" })}
                </dt>
                <dd className="mt-1 font-medium">{t(badge.hint)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {t({ zh: "到期时间", en: "Expires" })}
                </dt>
                <dd className="mt-1 font-medium">
                  {status?.expires_at
                    ? status.expires_at.slice(0, 10)
                    : t({ zh: "长期有效", en: "No expiry" })}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {t({ zh: "剩余天数", en: "Days left" })}
                </dt>
                <dd className="mt-1 font-medium">
                  {badge.daysLeft === null
                    ? t({ zh: "不限", en: "Unlimited" })
                    : t({
                        zh: `${badge.daysLeft} 天`,
                        en: `${badge.daysLeft} day${badge.daysLeft === 1 ? "" : "s"}`,
                      })}
                </dd>
              </div>
            </dl>

            {enabled && (
              <div className="mt-4 flex flex-wrap gap-2">
                {COURSE_ADMIN_LINKS[course.key].map((link) => (
                  <Link
                    key={link.to}
                    to={link.to}
                    className="inline-flex items-center gap-1 rounded-full border border-border/60 px-3 py-1.5 text-xs text-foreground transition-colors hover:border-primary/40 hover:text-primary"
                  >
                    {t(link.label)}
                    <ArrowRight className="size-3" aria-hidden="true" />
                  </Link>
                ))}
              </div>
            )}
          </div>
        )
      })}

      <p className="text-xs text-muted-foreground">
        {t({
          zh: "开通、续期与关闭由平台运营统一处理；本校只能查看状态、管理课程内容。",
          en: "Granting, renewing and closing courses is handled by the platform operator. Schools can review status and manage course content here.",
        })}
      </p>
    </div>
  )
}
