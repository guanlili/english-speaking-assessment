import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Plus, Power, PowerOff } from "lucide-react"
import { useState } from "react"
import {
  AdminService,
  type TenantAdminPublic,
  type TenantCreate,
  type TenantModuleAuditPublic,
} from "@/client"
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
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"
import { extractErrorMessage } from "@/utils"

const MODULE_META: Array<{
  key: ModuleKey
  zh: string
  en: string
}> = [
  { key: "speaking", zh: "口语", en: "Speaking" },
  { key: "vocabulary", zh: "单词", en: "Vocabulary" },
]

interface ModuleFormState {
  enabled: boolean
  effective: string
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

function moduleActive(row: TenantAdminPublic, key: ModuleKey): boolean {
  const m = moduleOf(row, key)
  if (!m?.enabled) return false
  if (m.effective_at && new Date(m.effective_at) > new Date()) return false
  return true
}

function onOff(
  value: boolean | null | undefined,
  t: (s: { zh: string; en: string }) => string,
): string {
  if (value === null || value === undefined)
    return t({ zh: "无记录", en: "none" })
  return value ? t({ zh: "开", en: "On" }) : t({ zh: "关", en: "Off" })
}

function enabledLabel(
  audit: TenantModuleAuditPublic,
  t: (s: { zh: string; en: string }) => string,
): string {
  return `${onOff(audit.enabled_before, t)} → ${onOff(audit.enabled_after, t)}`
}

function effectiveLabel(
  audit: TenantModuleAuditPublic,
  t: (s: { zh: string; en: string }) => string,
  lang: "zh" | "en",
): string {
  const fmt = (iso: string | null | undefined) =>
    iso ? formatDateTime(iso, lang) : t({ zh: "立即", en: "now" })
  return `${fmt(audit.effective_at_before)} → ${fmt(audit.effective_at_after)}`
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
  const [moduleDialog, setModuleDialog] = useState<{
    id: string
    slug: string
    name: string
  } | null>(null)
  const [moduleForm, setModuleForm] = useState<
    Record<ModuleKey, ModuleFormState>
  >({
    speaking: { enabled: false, effective: "" },
    vocabulary: { enabled: false, effective: "" },
  })

  const { data, isPending } = useQuery({
    queryKey: ["admin", "tenants"],
    queryFn: () => AdminService.listTenants(),
  })

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
    setModuleForm({
      speaking: {
        enabled: moduleActive(row, "speaking"),
        effective: toLocalInput(moduleOf(row, "speaking")?.effective_at),
      },
      vocabulary: {
        enabled: moduleActive(row, "vocabulary"),
        effective: toLocalInput(moduleOf(row, "vocabulary")?.effective_at),
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
      enabled: boolean
      effective_at: string | null
    }) =>
      AdminService.updateTenantModule({
        tenant_id: p.id,
        module_key: p.module_key,
        tenantModuleUpdate: {
          enabled: p.enabled,
          effective_at: p.effective_at,
        },
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
    const form = moduleForm[key]
    const effective_at = form.effective
      ? new Date(form.effective).toISOString()
      : null
    moduleMutation.mutate({
      id: moduleDialog.id,
      module_key: key,
      enabled: form.enabled,
      effective_at,
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
        {isPending ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t({ zh: "学校码", en: "Code" })}</TableHead>
                  <TableHead>{t({ zh: "名称", en: "Name" })}</TableHead>
                  <TableHead>{t({ zh: "状态", en: "Status" })}</TableHead>
                  <TableHead>{t({ zh: "模块", en: "Modules" })}</TableHead>
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
                {(data ?? []).map((row) => (
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
                          const active = moduleActive(row, meta.key)
                          const rowMeta = moduleOf(row, meta.key)
                          const future =
                            active === false &&
                            rowMeta?.enabled &&
                            rowMeta.effective_at &&
                            new Date(rowMeta.effective_at) > new Date()
                          return (
                            <Badge
                              key={meta.key}
                              variant={active ? "default" : "secondary"}
                            >
                              {t({ zh: meta.zh, en: meta.en })}{" "}
                              {future
                                ? t({ zh: "待生效", en: "Scheduled" })
                                : active
                                  ? t({ zh: "开", en: "On" })
                                  : t({ zh: "关", en: "Off" })}
                            </Badge>
                          )
                        })}
                      </div>
                    </TableCell>
                    <TableCell>{row.user_count}</TableCell>
                    <TableCell className="font-mono text-xs">
                      /s/{row.slug}/login
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="mr-2"
                        onClick={() => openModuleDialog(row)}
                      >
                        {t({ zh: "模块", en: "Modules" })}
                      </Button>
                      {row.status === "active" ? (
                        <Button
                          variant="outline"
                          size="sm"
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
                          onClick={() =>
                            statusMutation.mutate({
                              id: row.id,
                              status: "active",
                            })
                          }
                        >
                          <Power className="mr-2 size-4" aria-hidden="true" />
                          {t({ zh: "恢复", en: "Resume" })}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
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
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "模块授权", en: "Module access" })} ·{" "}
              {moduleDialog?.slug}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "整校开关：未开通的模块师生不可见；生效时间留空即立即生效。",
                en: "School-wide switches: students and teachers cannot see a disabled module. Leave effective time empty to apply now.",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-6">
            {MODULE_META.map((meta) => {
              const form = moduleForm[meta.key]
              const metaRow = moduleOf(
                (data ?? []).find((row) => row.id === moduleDialog?.id),
                meta.key,
              )
              return (
                <div
                  key={meta.key}
                  className="grid gap-3 rounded-2xl border p-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <Checkbox
                        id={`${meta.key}-enabled`}
                        checked={form.enabled}
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
                        {t({ zh: meta.zh, en: meta.en })}
                      </label>
                    </div>
                    <LoadingButton
                      size="sm"
                      loading={moduleMutation.isPending}
                      onClick={() => saveModule(meta.key)}
                    >
                      {t({ zh: "保存", en: "Save" })}
                    </LoadingButton>
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor={`${meta.key}-effective`}>
                      {t({
                        zh: "生效时间（选填，留空立即生效）",
                        en: "Effective at (optional, empty = now)",
                      })}
                    </Label>
                    <Input
                      id={`${meta.key}-effective`}
                      type="datetime-local"
                      className="min-h-11 text-base"
                      value={form.effective}
                      disabled={!form.enabled}
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
                    <p className="text-xs text-muted-foreground">
                      {metaRow?.updated_at
                        ? t({
                            zh: `上次更新：${formatDateTime(metaRow.updated_at, lang)}`,
                            en: `Last updated: ${formatDateTime(metaRow.updated_at, lang)}`,
                          })
                        : t({
                            zh: "当前无授权记录（视为关闭）",
                            en: "No record yet (treated as disabled)",
                          })}
                      {metaRow?.updated_by ? ` · ${metaRow.updated_by}` : ""}
                    </p>
                  </div>
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
                <div className="max-h-64 overflow-y-auto rounded-2xl border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t({ zh: "模块", en: "Module" })}</TableHead>
                        <TableHead>{t({ zh: "变更", en: "Change" })}</TableHead>
                        <TableHead>
                          {t({ zh: "生效时间", en: "Effective" })}
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
                              {effectiveLabel(audit, t, lang)}
                            </TableCell>
                            <TableCell className="font-mono text-xs">
                              {audit.actor_operator_id ?? "–"}
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
