import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { BarChart3, Plus, Power, PowerOff } from "lucide-react"
import { useState } from "react"
import {
  AdminService,
  type TenantAdminPublic,
  type TenantCreate,
  type TenantModuleAuditPublic,
  type TenantModuleUpdate,
  type TenantUsageMetrics,
  type TenantUsageSummaryItem,
} from "@/client"
import { TenantUsageDialog } from "@/components/Admin/TenantUsageDialog"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
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
import type { ModuleKey } from "@/hooks/useModules"
import type { BiString, Lang } from "@/lib/i18n"
import { useI18n } from "@/lib/i18n"
import {
  type BadgeTone,
  describeModuleBadge,
  GRANT_TYPE_LABELS,
  type GrantType,
  type ModuleFormDraft,
  normalizeGrantType,
  readCompactUsage,
  validateModuleForm,
} from "@/lib/tenantModules"
import { formatDateTime } from "@/lib/time"
import { extractErrorMessage } from "@/utils"

const MODULE_META: Array<{ key: ModuleKey; name: BiString }> = [
  { key: "speaking", name: { zh: "口语", en: "Speaking" } },
  { key: "vocabulary", name: { zh: "单词", en: "Vocabulary" } },
]

const TONE_VARIANT: Record<
  BadgeTone,
  "default" | "secondary" | "destructive" | "outline"
> = {
  muted: "secondary",
  outline: "outline",
  active: "default",
  destructive: "destructive",
}

function moduleOf(row: TenantAdminPublic | undefined, key: ModuleKey) {
  return row?.modules?.find((m) => m.module_key === key)
}

function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function onOff(
  value: boolean | null | undefined,
  t: (s: BiString) => string,
): string {
  if (value === null || value === undefined)
    return t({ zh: "无记录", en: "none" })
  return value ? t({ zh: "开", en: "On" }) : t({ zh: "关", en: "Off" })
}

function grantLabel(
  value: string | null | undefined,
  t: (s: BiString) => string,
): string {
  if (value === null || value === undefined) return "–"
  return t(GRANT_TYPE_LABELS[normalizeGrantType(value)])
}

/** 操作人不展示内部 UUID：有值统一归为平台运营，无值显示 –。 */
function operatorLabel(
  id: string | null | undefined,
  t: (s: BiString) => string,
): string {
  if (!id) return "–"
  return t({ zh: "平台运营", en: "Platform operator" })
}

function enabledLabel(
  audit: TenantModuleAuditPublic,
  t: (s: BiString) => string,
): string {
  return `${onOff(audit.enabled_before, t)} → ${onOff(audit.enabled_after, t)}`
}

function grantTypeLabel(
  audit: TenantModuleAuditPublic,
  t: (s: BiString) => string,
): string {
  return `${grantLabel(audit.grant_type_before, t)} → ${grantLabel(audit.grant_type_after, t)}`
}

function effectiveLabel(
  audit: TenantModuleAuditPublic,
  t: (s: BiString) => string,
  lang: Lang,
): string {
  const fmt = (iso: string | null | undefined) =>
    iso ? formatDateTime(iso, lang) : t({ zh: "立即", en: "now" })
  return `${fmt(audit.effective_at_before)} → ${fmt(audit.effective_at_after)}`
}

function expiryLabel(
  audit: TenantModuleAuditPublic,
  t: (s: BiString) => string,
  lang: Lang,
): string {
  const fmt = (iso: string | null | undefined) =>
    iso ? formatDateTime(iso, lang) : t({ zh: "长期", en: "Long-term" })
  return `${fmt(audit.expires_at_before)} → ${fmt(audit.expires_at_after)}`
}

/** 列表紧凑两行用量：第一行师生，第二行作答/任务/完成人数。无数据显示 `–`。 */
function CompactUsageCell({
  metrics,
}: {
  metrics: TenantUsageMetrics | null | undefined
}) {
  const { t } = useI18n()
  if (!metrics) {
    return <TableCell className="text-muted-foreground">–</TableCell>
  }
  const u = readCompactUsage(metrics)
  return (
    <TableCell>
      <div className="text-xs leading-relaxed">
        <div>
          {t({
            zh: `师 ${u.teachers} 生 ${u.students}`,
            en: `T ${u.teachers} · S ${u.students}`,
          })}
        </div>
        <div>
          {t({
            zh: `答 ${u.answers} 任 ${u.tasks} 完 ${u.completed}`,
            en: `A ${u.answers} · T ${u.tasks} · C ${u.completed}`,
          })}
        </div>
      </div>
    </TableCell>
  )
}

/**
 * 多租户 D2：平台运营的学校管理（开校/停用/改名）。
 * 停用即挡新登录（入口 404），学校与数据永不物理删除；
 * 默认学校为租户锚点不允许停用（后端同样守卫）。
 */
function SchoolsAdminPage() {
  const { t, lang } = useI18n()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState<TenantCreate>({
    slug: "",
    name_zh: "",
    name_en: null,
  })
  const [pending, setPending] = useState<{
    id: string
    action: "pause" | "resume"
    name: string
  } | null>(null)
  const [filter, setFilter] = useState<"all" | "expiring">("all")
  const [moduleDialog, setModuleDialog] = useState<{
    id: string
    slug: string
    name: string
  } | null>(null)
  const [moduleForm, setModuleForm] = useState<
    Record<ModuleKey, ModuleFormDraft>
  >({
    speaking: {
      enabled: false,
      effective: "",
      expires: "",
      grant_type: "manual",
    },
    vocabulary: {
      enabled: false,
      effective: "",
      expires: "",
      grant_type: "manual",
    },
  })
  const [moduleErrors, setModuleErrors] = useState<
    Partial<Record<ModuleKey, BiString>>
  >({})
  const [usageTenant, setUsageTenant] = useState<{
    id: string
    slug: string
    name_zh: string
  } | null>(null)

  const { data, isPending } = useQuery({
    queryKey: ["admin", "tenants", filter],
    queryFn: () =>
      AdminService.listTenants(
        filter === "expiring" ? { expiring_within_days: 7 } : {},
      ),
  })

  // 用量汇总一次请求；失败不拖垮学校列表（单元格回退 `–`）。
  const usageQuery = useQuery({
    queryKey: ["admin", "tenants", "usage-summary"],
    queryFn: () => AdminService.usageSummary(),
  })
  const usageByTenant = new Map<string, TenantUsageSummaryItem>(
    (usageQuery.data?.items ?? []).map((item) => [item.tenant_id, item]),
  )

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "tenants"] })

  const auditQuery = useQuery({
    queryKey: ["admin", "tenants", moduleDialog?.id, "module-audit"],
    queryFn: () =>
      AdminService.listTenantModuleAudit({ tenant_id: moduleDialog!.id }),
    enabled: moduleDialog !== null,
  })

  const openModuleDialog = (row: TenantAdminPublic) => {
    setModuleDialog({ id: row.id, slug: row.slug, name: row.name_zh })
    setModuleErrors({})
    setModuleForm({
      speaking: {
        enabled: moduleOf(row, "speaking")?.enabled ?? false,
        effective: toLocalInput(
          moduleOf(row, "speaking")?.effective_at ??
            moduleOf(row, "speaking")?.starts_at,
        ),
        expires: toLocalInput(moduleOf(row, "speaking")?.expires_at),
        grant_type: normalizeGrantType(moduleOf(row, "speaking")?.grant_type),
      },
      vocabulary: {
        enabled: moduleOf(row, "vocabulary")?.enabled ?? false,
        effective: toLocalInput(
          moduleOf(row, "vocabulary")?.effective_at ??
            moduleOf(row, "vocabulary")?.starts_at,
        ),
        expires: toLocalInput(moduleOf(row, "vocabulary")?.expires_at),
        grant_type: normalizeGrantType(moduleOf(row, "vocabulary")?.grant_type),
      },
    })
  }

  const createMutation = useMutation({
    mutationFn: (body: TenantCreate) =>
      AdminService.createTenant({ tenantCreate: body }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "学校已创建", en: "School created" }))
      setCreateOpen(false)
      setForm({ slug: "", name_zh: "", name_en: null })
      void invalidate()
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const statusMutation = useMutation({
    mutationFn: (p: { id: string; status: "active" | "paused" }) =>
      AdminService.updateTenant({
        tenant_id: p.id,
        tenantUpdate: { status: p.status },
      }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "状态已更新", en: "Status updated" }))
      setPending(null)
      void invalidate()
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const moduleMutation = useMutation({
    mutationFn: (p: {
      id: string
      module_key: ModuleKey
      body: TenantModuleUpdate
    }) =>
      AdminService.updateTenantModule({
        tenant_id: p.id,
        module_key: p.module_key,
        tenantModuleUpdate: p.body,
      }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "模块授权已更新", en: "Module updated" }))
      void invalidate()
      if (moduleDialog) {
        void queryClient.invalidateQueries({
          queryKey: ["admin", "tenants", moduleDialog.id, "module-audit"],
        })
      }
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const saveModule = (key: ModuleKey) => {
    if (!moduleDialog) return
    const draft = moduleForm[key]
    const result = validateModuleForm(draft)
    if (result.error) {
      setModuleErrors((prev) => ({ ...prev, [key]: result.error }))
      return
    }
    setModuleErrors((prev) => ({ ...prev, [key]: undefined }))
    moduleMutation.mutate({
      id: moduleDialog.id,
      module_key: key,
      body: {
        enabled: draft.enabled,
        effective_at: result.effective_at,
        expires_at: result.expires_at,
        grant_type: result.grant_type,
      },
    })
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle className="text-xl">
              {t({ zh: "学校管理", en: "Schools" })}
            </CardTitle>
            <CardDescription>
              {t({
                zh: "开校后把专属登录链接发给该校管理员即可使用；停用立即挡新登录，数据保留不删",
                en: "Share the school sign-in link after creation; pausing blocks new sign-ins, data is kept",
              })}
            </CardDescription>
          </div>
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 size-4" aria-hidden="true" />
            {t({ zh: "开新学校", en: "New school" })}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Select
            value={filter}
            onValueChange={(next) => setFilter(next as "all" | "expiring")}
          >
            <SelectTrigger data-testid="admin-schools-filter" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">
                {t({ zh: "全部学校", en: "All schools" })}
              </SelectItem>
              <SelectItem value="expiring">
                {t({ zh: "7 天内到期", en: "Expiring in 7 days" })}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        {isPending ? (
          <Skeleton className="h-48 w-full" />
        ) : (data ?? []).length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            {filter === "expiring"
              ? t({
                  zh: "近 7 天内没有即将到期的学校",
                  en: "No schools expiring within the next 7 days",
                })
              : t({ zh: "暂无学校", en: "No schools yet" })}
          </p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table data-testid="admin-schools-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>{t({ zh: "学校码", en: "Code" })}</TableHead>
                    <TableHead>{t({ zh: "名称", en: "Name" })}</TableHead>
                    <TableHead>{t({ zh: "状态", en: "Status" })}</TableHead>
                    <TableHead>{t({ zh: "模块", en: "Modules" })}</TableHead>
                    <TableHead>{t({ zh: "近 7 天", en: "Last 7d" })}</TableHead>
                    <TableHead>
                      {t({ zh: "近 30 天", en: "Last 30d" })}
                    </TableHead>
                    <TableHead>{t({ zh: "账号数", en: "Users" })}</TableHead>
                    <TableHead>
                      {t({ zh: "登录入口", en: "Sign-in link" })}
                    </TableHead>
                    <TableHead className="text-right">
                      {t({ zh: "操作", en: "Actions" })}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data ?? []).map((row) => {
                    const usage = usageByTenant.get(row.id)
                    return (
                      <TableRow key={row.id}>
                        <TableCell className="font-mono">{row.slug}</TableCell>
                        <TableCell>{row.name_zh}</TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              row.status === "active" ? "default" : "secondary"
                            }
                          >
                            {row.status === "active"
                              ? t({ zh: "使用中", en: "Active" })
                              : t({ zh: "已停用", en: "Paused" })}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {MODULE_META.map((meta) => {
                              const badge = describeModuleBadge(
                                moduleOf(row, meta.key),
                              )
                              return (
                                <Badge
                                  key={meta.key}
                                  variant={TONE_VARIANT[badge.tone]}
                                  title={t(badge.hint)}
                                >
                                  {t(meta.name)} {t(badge.label)}
                                </Badge>
                              )
                            })}
                          </div>
                        </TableCell>
                        <CompactUsageCell metrics={usage?.summary_7d} />
                        <CompactUsageCell metrics={usage?.summary_30d} />
                        <TableCell>{row.user_count}</TableCell>
                        <TableCell className="font-mono text-xs">
                          /s/{row.slug}/login
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex flex-wrap justify-end gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="min-h-10"
                              onClick={() => openModuleDialog(row)}
                            >
                              {t({ zh: "模块", en: "Modules" })}
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              className="min-h-10"
                              data-testid="tenant-usage-button"
                              onClick={() =>
                                setUsageTenant({
                                  id: row.id,
                                  slug: row.slug,
                                  name_zh: row.name_zh,
                                })
                              }
                            >
                              <BarChart3
                                className="mr-2 size-4"
                                aria-hidden="true"
                              />
                              {t({ zh: "用量", en: "Usage" })}
                            </Button>
                            {row.status === "active" ? (
                              <Button
                                variant="outline"
                                size="sm"
                                className="min-h-10"
                                onClick={() =>
                                  setPending({
                                    id: row.id,
                                    action: "pause",
                                    name: row.name_zh,
                                  })
                                }
                              >
                                <PowerOff
                                  className="mr-2 size-4"
                                  aria-hidden="true"
                                />
                                {t({ zh: "停用", en: "Pause" })}
                              </Button>
                            ) : (
                              <Button
                                variant="outline"
                                size="sm"
                                className="min-h-10"
                                onClick={() =>
                                  statusMutation.mutate({
                                    id: row.id,
                                    status: "active",
                                  })
                                }
                              >
                                <Power
                                  className="mr-2 size-4"
                                  aria-hidden="true"
                                />
                                {t({ zh: "恢复", en: "Resume" })}
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
            <p className="mt-2 text-xs text-muted-foreground sm:hidden">
              {t({
                zh: "表格较宽，可左右滑动查看完整信息",
                en: "The table is wide; swipe horizontally to see all columns",
              })}
            </p>
          </>
        )}
      </CardContent>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t({ zh: "开新学校", en: "New school" })}</DialogTitle>
            <DialogDescription>
              {t({
                zh: "学校码进入登录链接（小写字母/数字/连字符），创建后立即生效",
                en: "The code appears in the sign-in link (lowercase/digits/hyphens); effective immediately",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <Label htmlFor="slug">
                {t({ zh: "学校码", en: "School code" })}{" "}
                <span className="text-destructive">*</span>
              </Label>
              <Input
                id="slug"
                className="min-h-11 text-base"
                placeholder="e.g. school2"
                value={form.slug}
                onChange={(e) => setForm({ ...form, slug: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="name-zh">
                {t({ zh: "学校名称（中文）", en: "School name (Chinese)" })}{" "}
                <span className="text-destructive">*</span>
              </Label>
              <Input
                id="name-zh"
                className="min-h-11 text-base"
                value={form.name_zh}
                onChange={(e) => setForm({ ...form, name_zh: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="name-en">
                {t({
                  zh: "名称（英文，选填）",
                  en: "Name (English, optional)",
                })}
              </Label>
              <Input
                id="name-en"
                className="min-h-11 text-base"
                value={form.name_en ?? ""}
                onChange={(e) =>
                  setForm({ ...form, name_en: e.target.value || null })
                }
              />
            </div>
          </div>
          <DialogFooter>
            <LoadingButton
              className="w-full sm:w-auto"
              loading={createMutation.isPending}
              disabled={!form.slug || !form.name_zh}
              onClick={() => createMutation.mutate(form)}
            >
              {t({ zh: "创建", en: "Create" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={moduleDialog !== null}
        onOpenChange={(open) => !open && setModuleDialog(null)}
      >
        <DialogContent className="max-w-2xl" data-testid="admin-module-dialog">
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "模块授权", en: "Module access" })} ·{" "}
              {moduleDialog?.slug}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "整校开关：未开通的模块师生不可见；生效时间留空即立即生效，到期时间留空即长期。",
                en: "School-wide switches: students and teachers cannot see a disabled module. Leave effective time empty to apply now, expiry empty for a long-term license.",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-6">
            {MODULE_META.map((meta) => {
              const formState = moduleForm[meta.key]
              const metaRow = moduleOf(
                (data ?? []).find((row) => row.id === moduleDialog?.id),
                meta.key,
              )
              const badge = describeModuleBadge(metaRow)
              const error = moduleErrors[meta.key]
              return (
                <div
                  key={meta.key}
                  className="grid gap-3 rounded-2xl border p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <Checkbox
                        id={`${meta.key}-enabled`}
                        checked={formState.enabled}
                        onCheckedChange={(checked) =>
                          setModuleForm((prev) => ({
                            ...prev,
                            [meta.key]: {
                              ...prev[meta.key],
                              enabled: checked === true,
                            },
                          }))
                        }
                      />
                      <label htmlFor={`${meta.key}-enabled`}>
                        {t(meta.name)}
                      </label>
                      <Badge variant={TONE_VARIANT[badge.tone]}>
                        {t(badge.label)}
                      </Badge>
                    </div>
                    <LoadingButton
                      size="sm"
                      className="min-h-10"
                      loading={moduleMutation.isPending}
                      onClick={() => saveModule(meta.key)}
                    >
                      {t({ zh: "保存", en: "Save" })}
                    </LoadingButton>
                  </div>

                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="grid gap-2">
                      <Label htmlFor={`${meta.key}-grant`}>
                        {t({ zh: "授权类型", en: "Grant type" })}
                      </Label>
                      <Select
                        value={formState.grant_type}
                        onValueChange={(next) =>
                          setModuleForm((prev) => ({
                            ...prev,
                            [meta.key]: {
                              ...prev[meta.key],
                              grant_type: next as GrantType,
                            },
                          }))
                        }
                      >
                        <SelectTrigger
                          id={`${meta.key}-grant`}
                          className="min-h-11 w-full"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="trial">
                            {t(GRANT_TYPE_LABELS.trial)}
                          </SelectItem>
                          <SelectItem value="paid">
                            {t(GRANT_TYPE_LABELS.paid)}
                          </SelectItem>
                          <SelectItem value="manual">
                            {t(GRANT_TYPE_LABELS.manual)}
                          </SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor={`${meta.key}-effective`}>
                        {t({
                          zh: "开始时间（选填，留空立即生效）",
                          en: "Effective at (optional, empty = now)",
                        })}
                      </Label>
                      <Input
                        id={`${meta.key}-effective`}
                        type="datetime-local"
                        className="min-h-11 text-base"
                        value={formState.effective}
                        disabled={!formState.enabled}
                        onChange={(e) =>
                          setModuleForm((prev) => ({
                            ...prev,
                            [meta.key]: {
                              ...prev[meta.key],
                              effective: e.target.value,
                            },
                          }))
                        }
                      />
                    </div>
                    <div className="grid gap-2 sm:col-span-2">
                      <Label htmlFor={`${meta.key}-expires`}>
                        {t({
                          zh: "到期时间（选填，留空长期；试用必填）",
                          en: "Expiry (optional, empty = long-term; required for trial)",
                        })}
                      </Label>
                      <Input
                        id={`${meta.key}-expires`}
                        type="datetime-local"
                        className="min-h-11 text-base"
                        value={formState.expires}
                        disabled={!formState.enabled}
                        onChange={(e) =>
                          setModuleForm((prev) => ({
                            ...prev,
                            [meta.key]: {
                              ...prev[meta.key],
                              expires: e.target.value,
                            },
                          }))
                        }
                      />
                    </div>
                  </div>

                  {error && (
                    <p className="text-xs text-destructive">{t(error)}</p>
                  )}

                  {badge.daysLeft !== null && (
                    <p className="text-xs text-muted-foreground">
                      {t({
                        zh: `剩余 ${badge.daysLeft} 天`,
                        en: `${badge.daysLeft} days left`,
                      })}
                    </p>
                  )}

                  <p className="text-xs text-muted-foreground">
                    {metaRow?.updated_at
                      ? t({
                          zh: `上次更新：${formatDateTime(metaRow.updated_at, lang)}`,
                          en: `Last updated: ${formatDateTime(metaRow.updated_at, lang)}`,
                        })
                      : t({
                          zh: "当前无授权记录（视为未开通）",
                          en: "No record yet (treated as not granted)",
                        })}
                    {metaRow?.updated_by
                      ? ` · ${operatorLabel(metaRow.updated_by, t)}`
                      : ""}
                  </p>
                </div>
              )
            })}

            <section
              aria-label={t({ zh: "变更历史", en: "Change history" })}
              className="grid gap-2"
            >
              <p className="text-xs font-semibold tracking-[0.18em] text-muted-foreground">
                {t({ zh: "变更历史", en: "Change history" })}
              </p>
              {auditQuery.isPending ? (
                <Skeleton className="h-20 w-full" />
              ) : (auditQuery.data ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {t({ zh: "暂无变更记录", en: "No change records" })}
                </p>
              ) : (
                <div className="max-h-64 overflow-auto rounded-2xl border">
                  <Table
                    data-testid="admin-module-audit-table"
                    className="min-w-[880px]"
                  >
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t({ zh: "模块", en: "Module" })}</TableHead>
                        <TableHead>{t({ zh: "开关", en: "Switch" })}</TableHead>
                        <TableHead>
                          {t({ zh: "类型", en: "Grant type" })}
                        </TableHead>
                        <TableHead>
                          {t({ zh: "开始时间", en: "Effective" })}
                        </TableHead>
                        <TableHead>
                          {t({ zh: "到期时间", en: "Expiry" })}
                        </TableHead>
                        <TableHead>
                          {t({ zh: "操作人", en: "Operator" })}
                        </TableHead>
                        <TableHead>{t({ zh: "时间", en: "When" })}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(auditQuery.data ?? []).map(
                        (audit: TenantModuleAuditPublic) => (
                          <TableRow key={audit.id}>
                            <TableCell className="font-mono text-xs">
                              {audit.module_key}
                            </TableCell>
                            <TableCell className="text-xs">
                              {enabledLabel(audit, t)}
                            </TableCell>
                            <TableCell className="text-xs">
                              {grantTypeLabel(audit, t)}
                            </TableCell>
                            <TableCell className="text-xs">
                              {effectiveLabel(audit, t, lang)}
                            </TableCell>
                            <TableCell className="text-xs">
                              {expiryLabel(audit, t, lang)}
                            </TableCell>
                            <TableCell className="text-xs">
                              {operatorLabel(audit.actor_operator_id, t)}
                            </TableCell>
                            <TableCell className="text-xs">
                              {audit.created_at
                                ? formatDateTime(audit.created_at, lang)
                                : "–"}
                            </TableCell>
                          </TableRow>
                        ),
                      )}
                    </TableBody>
                  </Table>
                </div>
              )}
            </section>
          </div>
        </DialogContent>
      </Dialog>

      <TenantUsageDialog
        open={usageTenant !== null}
        onOpenChange={(open) => !open && setUsageTenant(null)}
        tenant={usageTenant}
      />

      <ConfirmDialog
        open={pending !== null}
        title={
          pending?.action === "pause"
            ? t({ zh: "停用学校", en: "Pause school" })
            : t({ zh: "恢复学校", en: "Resume school" })
        }
        description={t({
          zh: `停用后「${pending?.name ?? ""}」的师生将无法再登录（已在使用的会话到期后失效），数据全部保留。`,
          en: `Users of "${pending?.name ?? ""}" cannot sign in again (active sessions lapse at expiry); all data is kept.`,
        })}
        confirmText={
          pending?.action === "pause"
            ? t({ zh: "确认停用", en: "Pause" })
            : t({ zh: "确认恢复", en: "Resume" })
        }
        onConfirm={() => {
          if (pending) {
            statusMutation.mutate({
              id: pending.id,
              status: pending.action === "pause" ? "paused" : "active",
            })
          }
        }}
        onOpenChange={(open) => !open && setPending(null)}
      />
    </Card>
  )
}

export const Route = createFileRoute("/_layout/admin/schools")({
  component: SchoolsAdminPage,
})
