import { Clock, ShieldAlert, TriangleAlert } from "lucide-react"
import type { ModuleStatus } from "@/client"
import type { ModuleKey } from "@/hooks/useModules"
import type { BiString } from "@/lib/bi"
import { useI18n } from "@/lib/i18n"
import {
  type BannerEntry,
  type BannerLevel,
  daysLeftEn,
  describeBanner,
} from "@/lib/tenantModules"

const MODULE_NAMES: Record<ModuleKey, BiString> = {
  speaking: { zh: "口语", en: "Speaking" },
  vocabulary: { zh: "单词", en: "Vocabulary" },
}

const LEVEL_STYLES: Record<Exclude<BannerLevel, "none">, string> = {
  trial: "border-primary/30 bg-primary/5 text-foreground",
  warning:
    "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200",
  critical: "border-destructive/40 bg-destructive/5 text-destructive",
  expired: "border-destructive/40 bg-destructive/5 text-destructive",
}

const LEVEL_ICONS: Record<Exclude<BannerLevel, "none">, typeof Clock> = {
  trial: Clock,
  warning: TriangleAlert,
  critical: ShieldAlert,
  expired: ShieldAlert,
}

interface BannerRow {
  key: ModuleKey
  entry: BannerEntry
}

/**
 * 学校管理员后台的模块到期 / 试用提醒横幅。
 *
 * 仅 school_admin（兼容旧值 admin）可见；平台运营 / 教师 / 学生不显示。
 * 口径来自后端 `/modules/me` 的 `statuses`：
 * - active + trial 且剩余 ≤30 天：逐档提示（≤7 warning，≤1 destructive）；
 * - expired：入口已关闭提醒；
 * - disabled / not_granted / scheduled 不提示。
 * 两个模块同时命中时合并在同一横幅内逐行列出。
 */
export function TenantModuleBanner({
  statuses,
  role,
}: {
  statuses?: ModuleStatus[]
  role?: string | null
}) {
  const { t } = useI18n()

  const isSchoolAdmin = role === "school_admin" || role === "admin"
  if (!isSchoolAdmin) return null

  const byKey = new Map<string, ModuleStatus>(
    (statuses ?? []).map((s) => [s.module_key, s]),
  )

  const rows: BannerRow[] = (Object.keys(MODULE_NAMES) as ModuleKey[]).flatMap(
    (key) => {
      const entry = describeBanner(byKey.get(key))
      return entry.level === "none" ? [] : [{ key, entry }]
    },
  )

  if (rows.length === 0) return null

  return (
    <div
      data-testid="tenant-trial-banner"
      className="mb-4 flex flex-col gap-2"
      role="status"
    >
      {rows.map(({ key, entry }) => {
        const Icon = LEVEL_ICONS[entry.level as Exclude<BannerLevel, "none">]
        const name = t(MODULE_NAMES[key])
        const line: BiString =
          entry.level === "expired"
            ? {
                zh: `${name}模块已到期，入口已关闭；数据保留，请联系平台续期。`,
                en: `${name} module expired; entry closed. Data is retained. Contact the platform to renew.`,
              }
            : {
                zh: `${name}模块试用还剩 ${entry.daysLeft ?? 0} 天`,
                en: `${name} trial: ${daysLeftEn(entry.daysLeft)}`,
              }
        return (
          <div
            key={key}
            data-testid="tenant-trial-banner-item"
            data-level={entry.level}
            className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${LEVEL_STYLES[entry.level as Exclude<BannerLevel, "none">]}`}
          >
            <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <div className="min-w-0 space-y-1">
              <p className="font-medium">{t(line)}</p>
              {entry.level !== "expired" && (
                <p className="text-xs opacity-80">
                  {t({
                    zh: "到期后师生入口关闭，数据保留，请联系平台续期。",
                    en: "After expiry, teacher and student entry closes; data is retained. Contact the platform to renew.",
                  })}
                </p>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
