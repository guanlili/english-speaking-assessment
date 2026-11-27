import { useMutation, useQuery } from "@tanstack/react-query"
import { Download } from "lucide-react"
import { useEffect, useState } from "react"
import { AdminService, type TenantUsageMetrics } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import type { BiString } from "@/lib/bi"
import { useI18n } from "@/lib/i18n"
import {
  defaultUsageRange,
  mapLimitation,
  metricValue,
  type RangeValidation,
  USAGE_METRICS,
  usageCsvFilename,
  validateUsageRange,
} from "@/lib/tenantModules"
import { extractErrorMessage } from "@/utils"

interface TenantRef {
  id: string
  slug: string
  name_zh: string
}

const RANGE_ERRORS: Record<Exclude<RangeValidation, "ok">, BiString> = {
  missing: {
    zh: "请选择起止日期",
    en: "Select a start and end date",
  },
  invalid: {
    zh: "日期无效，或开始日期晚于结束日期",
    en: "Invalid dates, or start date after end date",
  },
  too_wide: {
    zh: "范围不能超过 366 天",
    en: "Range cannot exceed 366 days",
  },
}

function downloadBlob(blob: Blob | File, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  document.body.append(anchor)
  anchor.href = url
  anchor.download = filename
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/**
 * 单校按天用量弹窗（#517 B）：默认近 30 天（含今天），可改起止；
 * 顶部九项区间总量卡片，下面每日明细表；limitations 以浅色说明块逐条展示。
 * 只出聚合数，界面不出现任何学生 / 教师标识。
 */
export function TenantUsageDialog({
  open,
  onOpenChange,
  tenant,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  tenant: TenantRef | null
}) {
  const { t } = useI18n()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [from, setFrom] = useState("")
  const [to, setTo] = useState("")

  // 每次打开重置为默认近 30 天，避免上一所学校的残留范围影响新查询。
  useEffect(() => {
    if (open) {
      const range = defaultUsageRange(30)
      setFrom(range.from)
      setTo(range.to)
    }
  }, [open])

  const range = validateUsageRange(from, to)
  const rangeError = range === "ok" ? null : RANGE_ERRORS[range]

  const detailQuery = useQuery({
    queryKey: ["admin", "tenant-usage", tenant?.id, from, to],
    queryFn: () =>
      AdminService.tenantUsageDetail({ tenant_id: tenant!.id, from, to }),
    enabled: open && tenant !== null && range === "ok",
  })

  const csvMutation = useMutation({
    mutationFn: async () => {
      if (!tenant) throw new Error("no tenant")
      // CSV 二进制响应：按调用点声明 parseAs 拿 Blob（生成客户端 200 类型为 unknown）。
      const blob = (await AdminService.tenantUsageCsv(
        { tenant_id: tenant.id, from, to },
        { parseAs: "blob" },
      )) as Blob
      downloadBlob(blob, usageCsvFilename(tenant.slug, from, to))
    },
    onSuccess: () =>
      showSuccessToast(t({ zh: "CSV 已下载", en: "CSV downloaded" })),
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const totals: TenantUsageMetrics | undefined = detailQuery.data?.totals
  const days = detailQuery.data?.days ?? []
  const limitations = detailQuery.data?.limitations ?? []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl" data-testid="admin-usage-dialog">
        <DialogHeader>
          <DialogTitle>
            {t({ zh: "学校用量", en: "School usage" })} · {tenant?.slug}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "按本地自然日聚合的九项指标；区间总量为每日行求和，去重项单日去重。",
              en: "Nine metrics aggregated by local day; totals are daily sums, deduplicated within a single day.",
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid gap-2">
              <Label htmlFor="usage-from">
                {t({ zh: "开始日期", en: "From" })}
              </Label>
              <Input
                id="usage-from"
                type="date"
                className="min-h-11 text-base"
                value={from}
                max={to || undefined}
                onChange={(e) => setFrom(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="usage-to">
                {t({ zh: "结束日期", en: "To" })}
              </Label>
              <Input
                id="usage-to"
                type="date"
                className="min-h-11 text-base"
                value={to}
                min={from || undefined}
                onChange={(e) => setTo(e.target.value)}
              />
            </div>
            {rangeError && (
              <p className="text-xs text-destructive">{t(rangeError)}</p>
            )}
            <div className="ml-auto">
              <LoadingButton
                size="sm"
                variant="outline"
                loading={csvMutation.isPending}
                disabled={range !== "ok" || tenant === null}
                onClick={() => csvMutation.mutate()}
              >
                <Download className="mr-2 size-4" aria-hidden="true" />
                {t({ zh: "下载 CSV", en: "Download CSV" })}
              </LoadingButton>
            </div>
          </div>

          {limitations.length > 0 && (
            <div className="grid gap-1.5 rounded-xl border bg-muted/40 p-3 text-xs text-muted-foreground">
              <p className="font-medium text-foreground">
                {t({ zh: "口径说明", en: "Notes" })}
              </p>
              <ul className="list-disc space-y-1 pl-5">
                {limitations.map((text) => {
                  const mapped = mapLimitation(text)
                  return <li key={text}>{mapped ? t(mapped) : text}</li>
                })}
              </ul>
            </div>
          )}

          {detailQuery.isPending ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-3">
                {USAGE_METRICS.map((metric) => (
                  <div
                    key={metric.key}
                    className="rounded-xl border p-3"
                    data-testid={`usage-metric-${metric.key}`}
                  >
                    <p className="text-xs text-muted-foreground">
                      {t({ zh: metric.zh, en: metric.en })}
                    </p>
                    <p className="mt-1 text-lg font-semibold tabular-nums">
                      {metricValue(totals, metric.key)}
                    </p>
                  </div>
                ))}
              </div>

              <div className="overflow-x-auto rounded-xl border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t({ zh: "日期", en: "Date" })}</TableHead>
                      {USAGE_METRICS.map((metric) => (
                        <TableHead key={metric.key} className="text-right">
                          {t({ zh: metric.zh, en: metric.en })}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {days.length === 0 ? (
                      <TableRow>
                        <TableCell
                          colSpan={USAGE_METRICS.length + 1}
                          className="text-center text-muted-foreground"
                        >
                          {t({
                            zh: "所选范围内暂无数据",
                            en: "No data in range",
                          })}
                        </TableCell>
                      </TableRow>
                    ) : (
                      days.map((day) => (
                        <TableRow key={day.date}>
                          <TableCell className="font-mono text-xs">
                            {day.date}
                          </TableCell>
                          {USAGE_METRICS.map((metric) => (
                            <TableCell
                              key={metric.key}
                              className="text-right tabular-nums"
                            >
                              {metricValue(day, metric.key)}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
              {detailQuery.data?.timezone && (
                <p className="text-xs text-muted-foreground">
                  {t({ zh: "时区", en: "Timezone" })}:{" "}
                  {detailQuery.data.timezone}
                </p>
              )}
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t({ zh: "关闭", en: "Close" })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
