import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Download, Loader2, ShieldCheck } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import {
  AdminService,
  ApiError,
  type VocabularyLicenseStatusItem,
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
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { APP_NAME } from "@/config"
import { localDateStamp } from "@/lib/dates"
import { useI18n } from "@/lib/i18n"
import { formatDate, formatDateTime } from "@/lib/time"
import {
  describeQueryError,
  isDemoSource,
  isSafeHttpUrl,
  LICENSE_STATUS_ACTIVE,
  LICENSE_STATUS_EXPIRED,
  LICENSE_STATUS_EXPIRING,
  LICENSE_STATUS_MISSING,
  LICENSE_STATUS_NOT_REQUIRED,
  licenseStatusLabel,
  sourceTypeLabel,
} from "@/lib/vocabGovernance"

export const Route = createFileRoute("/_layout/admin/vocabulary-licenses")({
  component: VocabularyLicenseLedger,
  head: () => ({
    meta: [{ title: `授权台账 / License Ledger - ${APP_NAME}` }],
  }),
})

/** 台账四个统计桶（与后端 status 筛选口径对齐；not_required 并入有效）。 */
const STAT_BUCKETS = [
  LICENSE_STATUS_ACTIVE,
  LICENSE_STATUS_EXPIRING,
  LICENSE_STATUS_EXPIRED,
  LICENSE_STATUS_MISSING,
] as const

type StatBucket = (typeof STAT_BUCKETS)[number]

function statusVariant(status: string) {
  if (status === LICENSE_STATUS_EXPIRED || status === LICENSE_STATUS_MISSING) {
    return "destructive" as const
  }
  if (status === LICENSE_STATUS_EXPIRING) {
    return "secondary" as const
  }
  return "outline" as const
}

function matchesBucket(status: string, bucket: StatBucket): boolean {
  if (bucket === LICENSE_STATUS_ACTIVE) {
    return (
      status === LICENSE_STATUS_ACTIVE || status === LICENSE_STATUS_NOT_REQUIRED
    )
  }
  return status === bucket
}

function CredentialCell({
  item,
  t,
}: {
  item: VocabularyLicenseStatusItem
  t: (bi: { zh: string; en: string }) => string
}) {
  const ref = item.license_ref?.trim() || null
  const docUrl = item.authorization_doc_url?.trim() || null
  const safeDoc = isSafeHttpUrl(docUrl) ? docUrl : null
  const safeRef = ref && isSafeHttpUrl(ref) ? ref : null

  if (!ref && !safeDoc) {
    return <span className="text-muted-foreground">–</span>
  }

  return (
    <div className="flex min-w-32 flex-wrap items-center gap-x-2 gap-y-1">
      {ref && !safeRef && <span className="text-xs">{ref}</span>}
      {(safeRef || safeDoc) && (
        <a
          href={(safeDoc ?? safeRef) as string}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-primary underline-offset-2 hover:underline"
        >
          {t({ zh: "授权书", en: "Doc" })}
        </a>
      )}
    </div>
  )
}

function VocabularyLicenseLedger() {
  const { t, lang } = useI18n()
  const [tenant, setTenant] = useState("")
  const [book, setBook] = useState("")
  const [status, setStatus] = useState("")

  // 全量清单用于顶部统计卡（只读、limit 封顶 1000）；筛选结果走单独查询。
  const allQuery = useQuery({
    queryKey: ["admin", "vocab-license-status", "all"],
    queryFn: () => AdminService.adminListLicenseStatus({ limit: 1000 }),
  })

  const filteredQuery = useQuery({
    queryKey: [
      "admin",
      "vocab-license-status",
      "filtered",
      tenant,
      book,
      status,
    ],
    queryFn: () =>
      AdminService.adminListLicenseStatus({
        tenant: tenant.trim() || undefined,
        book: book.trim() || undefined,
        status: status || undefined,
        limit: 1000,
      }),
  })

  const allItems = allQuery.data?.items ?? []
  const rows = filteredQuery.data?.items ?? []

  const counts = useMemo(() => {
    const base: Record<StatBucket, number> = {
      [LICENSE_STATUS_ACTIVE]: 0,
      [LICENSE_STATUS_EXPIRING]: 0,
      [LICENSE_STATUS_EXPIRED]: 0,
      [LICENSE_STATUS_MISSING]: 0,
    }
    for (const item of allItems) {
      for (const bucket of STAT_BUCKETS) {
        if (matchesBucket(item.license_status, bucket)) {
          base[bucket] += 1
        }
      }
    }
    return base
  }, [allItems])

  const exportMutation = useMutation({
    mutationFn: () =>
      AdminService.adminExportLicenseCsv().then((r) => r as string),
    onSuccess: (text) => {
      const blob = new Blob([text], { type: "text/csv;charset=utf-8" })
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `vocabulary-license-all-${localDateStamp()}.csv`
      document.body.append(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      toast.success(t({ zh: "导出已开始。", en: "Export started." }))
    },
    onError: (error) => {
      const status = error instanceof ApiError ? error.status : undefined
      toast.error(t(describeQueryError(status)))
    },
  })

  const errorStatus =
    filteredQuery.error instanceof ApiError
      ? filteredQuery.error.status
      : undefined

  const statCards: Array<{
    bucket: StatBucket
    label: { zh: string; en: string }
  }> = [
    { bucket: LICENSE_STATUS_ACTIVE, label: { zh: "有效", en: "Active" } },
    {
      bucket: LICENSE_STATUS_EXPIRING,
      label: { zh: "临期", en: "Expiring soon" },
    },
    { bucket: LICENSE_STATUS_EXPIRED, label: { zh: "已过期", en: "Expired" } },
    { bucket: LICENSE_STATUS_MISSING, label: { zh: "缺失", en: "Missing" } },
  ]

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {t({ zh: "授权台账", en: "License Ledger" })}
          </h1>
          <p className="mt-1 max-w-3xl text-muted-foreground">
            {t({
              zh: "跨校词库当前授权状态只读台账：教材 / 授权引进来源须具备授权方与凭证；缺失、临期与过期条目请联系对应学校补齐。本页不提供授权修改入口。",
              en: "Read-only cross-school ledger of current word-book licenses. Textbook / licensed sources need an owner and a credential; follow up on missing, expiring or expired items with the school. No edit actions here.",
            })}
          </p>
        </div>
        <Button
          variant="outline"
          disabled={exportMutation.isPending || allQuery.isPending}
          onClick={() => void exportMutation.mutateAsync()}
        >
          {exportMutation.isPending ? (
            <Loader2 className="animate-spin" />
          ) : (
            <Download />
          )}
          {t({ zh: "导出 CSV", en: "Export CSV" })}
        </Button>
      </div>

      {/* 统计卡 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {statCards.map(({ bucket, label }) => (
          <Card key={bucket}>
            <CardContent className="py-4">
              <p className="text-xs text-muted-foreground">{t(label)}</p>
              <p className="mt-1 text-2xl font-bold tabular-nums">
                {allQuery.isPending ? "…" : counts[bucket]}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="flex flex-wrap items-center gap-3 space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldCheck className="size-4 text-primary" />
              {t({ zh: "学校 / 词库授权清单", en: "Books by school" })}
            </CardTitle>
            <CardDescription>
              {t({
                zh: "按学校、词库或授权状态筛选；凭证链接仅展示 http/https。",
                en: "Filter by school, book or license status. Only http/https credential links are shown.",
              })}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* 筛选区：触控目标 h-11、字号 base */}
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <label
                htmlFor="license-filter-tenant"
                className="text-sm font-medium"
              >
                {t({ zh: "学校", en: "School" })}
              </label>
              <Input
                id="license-filter-tenant"
                value={tenant}
                onChange={(event) => setTenant(event.target.value)}
                placeholder={t({
                  zh: "校名或码，如：王府",
                  en: "Name or slug, e.g. Wangfu",
                })}
                className="h-11 text-base"
              />
            </div>
            <div className="space-y-1.5">
              <label
                htmlFor="license-filter-book"
                className="text-sm font-medium"
              >
                {t({ zh: "词库", en: "Word book" })}
              </label>
              <Input
                id="license-filter-book"
                value={book}
                onChange={(event) => setBook(event.target.value)}
                placeholder={t({
                  zh: "词库标题关键词",
                  en: "Book title keyword",
                })}
                className="h-11 text-base"
              />
            </div>
            <div className="space-y-1.5">
              <label
                htmlFor="license-filter-status"
                className="text-sm font-medium"
              >
                {t({ zh: "授权状态", en: "License status" })}
              </label>
              <select
                id="license-filter-status"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                aria-label={t({
                  zh: "授权状态筛选",
                  en: "Filter by license status",
                })}
                className="h-11 w-full rounded-xl border border-input bg-card px-3 text-base text-foreground transition-colors hover:border-primary/35"
              >
                <option value="">
                  {t({ zh: "全部状态", en: "All statuses" })}
                </option>
                <option value={LICENSE_STATUS_ACTIVE}>
                  {t({ zh: "有效", en: "Active" })}
                </option>
                <option value={LICENSE_STATUS_EXPIRING}>
                  {t({ zh: "临期", en: "Expiring soon" })}
                </option>
                <option value={LICENSE_STATUS_EXPIRED}>
                  {t({ zh: "已过期", en: "Expired" })}
                </option>
                <option value={LICENSE_STATUS_MISSING}>
                  {t({ zh: "缺失", en: "Missing" })}
                </option>
              </select>
            </div>
          </div>

          {filteredQuery.isPending ? (
            <div role="status" className="py-6 text-base text-muted-foreground">
              {t({ zh: "正在加载授权台账…", en: "Loading license ledger…" })}
            </div>
          ) : filteredQuery.isError ? (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-destructive/40 bg-destructive/5 p-4">
              <p className="text-base text-destructive">
                {t(describeQueryError(errorStatus))}
              </p>
              <Button
                variant="outline"
                onClick={() => void filteredQuery.refetch()}
              >
                {t({ zh: "重试", en: "Retry" })}
              </Button>
            </div>
          ) : rows.length === 0 ? (
            <p className="py-6 text-base text-muted-foreground">
              {t({
                zh: "没有符合条件的词库授权记录。",
                en: "No book licenses match the filters.",
              })}
            </p>
          ) : (
            <>
              <p className="text-xs text-muted-foreground sm:hidden">
                {t({
                  zh: "横向滑动表格，可以查看完整字段。",
                  en: "Swipe the table sideways to see all fields.",
                })}
              </p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t({ zh: "学校", en: "School" })}</TableHead>
                      <TableHead>
                        {t({ zh: "词库", en: "Word book" })}
                      </TableHead>
                      <TableHead>
                        {t({ zh: "来源类型", en: "Source type" })}
                      </TableHead>
                      <TableHead>
                        {t({ zh: "授权状态", en: "License status" })}
                      </TableHead>
                      <TableHead>{t({ zh: "授权方", en: "Owner" })}</TableHead>
                      <TableHead>
                        {t({ zh: "到期日", en: "Expires at" })}
                      </TableHead>
                      <TableHead>
                        {t({ zh: "凭证", en: "Credential" })}
                      </TableHead>
                      <TableHead>
                        {t({ zh: "备注 / 登记时间", en: "Note / Registered" })}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((item) => (
                      <TableRow key={item.book_id}>
                        <TableCell className="max-w-40">
                          <span className="block truncate">
                            {item.tenant_name || item.tenant_slug || "–"}
                          </span>
                        </TableCell>
                        <TableCell className="max-w-56 font-semibold">
                          <span className="block truncate">{item.title}</span>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">
                            {t(sourceTypeLabel(item.source_type))}
                          </Badge>
                          {isDemoSource(item.source_type) && (
                            <Badge variant="secondary" className="ml-1.5">
                              {t({ zh: "演示", en: "Demo" })}
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant={statusVariant(item.license_status)}>
                            {t(licenseStatusLabel(item.license_status))}
                          </Badge>
                        </TableCell>
                        <TableCell className="max-w-40">
                          <span className="block truncate">
                            {item.license_owner?.trim() || "–"}
                          </span>
                        </TableCell>
                        <TableCell>
                          {item.license_expires_at
                            ? formatDate(item.license_expires_at, lang)
                            : "–"}
                        </TableCell>
                        <TableCell>
                          <CredentialCell item={item} t={t} />
                        </TableCell>
                        <TableCell className="max-w-48">
                          {item.license_note?.trim() ? (
                            <span className="block truncate text-xs text-muted-foreground">
                              {item.license_note.trim()}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">–</span>
                          )}
                          {item.created_at && (
                            <span className="block text-xs text-muted-foreground">
                              {formatDateTime(item.created_at, lang)}
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <p className="py-3 text-xs text-muted-foreground">
                {t({
                  zh: `共 ${filteredQuery.data?.total ?? rows.length} 条记录`,
                  en: `${filteredQuery.data?.total ?? rows.length} records`,
                })}
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
