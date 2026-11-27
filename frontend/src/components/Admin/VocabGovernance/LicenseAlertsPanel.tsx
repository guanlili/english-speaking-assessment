import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, ChevronDown, ChevronRight, XCircle } from "lucide-react"
import { useState } from "react"
import {
  ApiError,
  type VocabularyLicenseAlertItem,
  VocabularyService,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useI18n } from "@/lib/i18n"
import { formatDate } from "@/lib/time"
import {
  describeQueryError,
  isDemoSource,
  LICENSE_STATUS_EXPIRED,
  LICENSE_STATUS_EXPIRING,
  licenseStatusLabel,
  sourceTypeLabel,
} from "@/lib/vocabGovernance"

/** 临期窗口（天），与后端默认 LICENSE_EXPIRING_DAYS 对齐。 */
const EXPIRING_DAYS = 30

function alertStatusVariant(status: string) {
  return status === LICENSE_STATUS_EXPIRED
    ? "destructive"
    : status === LICENSE_STATUS_EXPIRING
      ? "secondary"
      : "outline"
}

/**
 * 授权到期提醒：30 天内临期与已过期的词库 / 词条汇总，可展开明细。
 * 平台运营会话不走学校端点，由父级按身份禁用。
 */
export function LicenseAlertsPanel({ enabled }: { enabled: boolean }) {
  const { t, lang } = useI18n()
  const [expanded, setExpanded] = useState(false)

  const alertsQuery = useQuery({
    queryKey: ["admin", "vocab-license-alerts", EXPIRING_DAYS],
    queryFn: () => VocabularyService.listLicenseAlerts({ days: EXPIRING_DAYS }),
    enabled,
  })

  if (!enabled) return null

  const alerts = alertsQuery.data ?? []
  const expiringCount = alerts.filter(
    (alert) => alert.license_status === LICENSE_STATUS_EXPIRING,
  ).length
  const expiredCount = alerts.filter(
    (alert) => alert.license_status === LICENSE_STATUS_EXPIRED,
  ).length
  const hasAlerts = alerts.length > 0

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="text-base">
            {t({ zh: "授权到期提醒", en: "License expiry alerts" })}{" "}
            <span className="text-sm font-normal text-muted-foreground">
              · {EXPIRING_DAYS} {t({ zh: "天内", en: "days" })}
            </span>
          </CardTitle>
          <CardDescription>
            {t({
              zh: "教材 / 授权引进来源临期或已过期的词库与词条；发布前会再次校验。",
              en: "Textbook / licensed books and words expiring soon or expired; publishing is re-checked against these.",
            })}
          </CardDescription>
        </div>
        {hasAlerts && (
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">
              {t({ zh: "临期", en: "Expiring" })} · {expiringCount}
            </Badge>
            <Badge variant="destructive">
              {t({ zh: "已过期", en: "Expired" })} · {expiredCount}
            </Badge>
            <Button
              variant="outline"
              size="sm"
              aria-expanded={expanded}
              onClick={() => setExpanded((prev) => !prev)}
            >
              {expanded ? <ChevronDown /> : <ChevronRight />}
              {t(
                expanded
                  ? { zh: "收起", en: "Collapse" }
                  : { zh: "展开", en: "Expand" },
              )}
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent className="pb-6">
        {alertsQuery.isPending ? (
          <div role="status">
            <Skeleton className="h-20 rounded-xl" />
          </div>
        ) : alertsQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {t(
              describeQueryError(
                alertsQuery.error instanceof ApiError
                  ? alertsQuery.error.status
                  : undefined,
              ),
            )}
          </p>
        ) : !hasAlerts ? (
          <p className="text-sm text-muted-foreground">
            {t({
              zh: "近 30 天没有临期或已过期的授权。",
              en: "No licenses expiring soon or expired in the last 30 days.",
            })}
          </p>
        ) : (
          expanded && (
            <ul className="space-y-3">
              {alerts.map((alert) => (
                <AlertRow
                  key={`${alert.target_type}-${alert.word_id ?? alert.book_id}`}
                  alert={alert}
                  lang={lang}
                  t={t}
                />
              ))}
            </ul>
          )
        )}
      </CardContent>
    </Card>
  )
}

function AlertRow({
  alert,
  lang,
  t,
}: {
  alert: VocabularyLicenseAlertItem
  lang: "zh" | "en"
  t: (bi: { zh: string; en: string }) => string
}) {
  const title = alert.target_type === "word" ? alert.headword : alert.book_title
  return (
    <li className="flex flex-wrap items-start gap-2 rounded-xl border border-border/70 bg-secondary/30 p-3">
      <Badge variant={alertStatusVariant(alert.license_status)}>
        {t(licenseStatusLabel(alert.license_status))}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 font-medium">
          <span className="truncate">{title}</span>
          <Badge variant="outline">
            {t(sourceTypeLabel(alert.source_type))}
          </Badge>
          {isDemoSource(alert.source_type) && (
            <Badge variant="destructive">
              {t({ zh: "演示 Mock", en: "Demo mock" })}
            </Badge>
          )}
        </p>
        <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
          <span>
            {t({ zh: "归属", en: "Book" })}：{alert.book_title}
          </span>
          {alert.license_owner && (
            <span>
              {t({ zh: "授权方", en: "Owner" })}：{alert.license_owner}
            </span>
          )}
          {alert.license_ref && (
            <span>
              {t({ zh: "凭证", en: "Ref" })}：{alert.license_ref}
            </span>
          )}
          {alert.license_expires_at && (
            <span className="inline-flex items-center gap-1">
              {alert.license_status === LICENSE_STATUS_EXPIRED ? (
                <XCircle className="size-3" />
              ) : (
                <AlertTriangle className="size-3" />
              )}
              {formatDate(alert.license_expires_at, lang)}
            </span>
          )}
        </p>
      </div>
    </li>
  )
}
