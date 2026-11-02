import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Plus, Power, PowerOff } from "lucide-react"
import { useState } from "react"
import { AdminService, type TenantCreate } from "@/client"
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
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"

/**
 * 多租户 D2：平台运营的学校管理（开校/停用/改名）。
 * 停用即挡新登录（入口 404），学校与数据永不物理删除；
 * 默认学校为租户锚点不允许停用（后端同样守卫）。
 */
function SchoolsAdminPage() {
  const { t } = useI18n()
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

  const { data, isPending } = useQuery({
    queryKey: ["admin", "tenants"],
    queryFn: () => AdminService.listTenants(),
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "tenants"] })

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
                    <TableCell>{row.user_count}</TableCell>
                    <TableCell className="font-mono text-xs">
                      /s/{row.slug}/login
                    </TableCell>
                    <TableCell className="text-right">
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
