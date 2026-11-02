import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Plus, UserRoundCog } from "lucide-react"
import { useState } from "react"
import { type MemberCreate, SchoolService } from "@/client"
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
 * 四角色完善：学校管理员的本校教师管理（/school/members）。
 * 建号自动落本校；停用即挡登录（数据保留）；重置密码供教师离职/忘密。
 * 学生账号走「我的课堂 → 导入学生」，不在此重复入口。
 */
function SchoolMembersPage() {
  const { t } = useI18n()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [form, setForm] = useState<MemberCreate>({
    email: "",
    full_name: null,
    password: "",
  })
  const [pendingToggle, setPendingToggle] = useState<{
    id: string
    active: boolean
    name: string
  } | null>(null)
  const [resetTarget, setResetTarget] = useState<{
    id: string
    name: string
  } | null>(null)
  const [newPassword, setNewPassword] = useState("")

  const { data, isPending } = useQuery({
    queryKey: ["school", "members", search],
    queryFn: () => SchoolService.listMembers({ q: search || undefined }),
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["school", "members"] })

  const createMutation = useMutation({
    mutationFn: (body: MemberCreate) =>
      SchoolService.createMember({ memberCreate: body }),
    onSuccess: () => {
      showSuccessToast(
        t({ zh: "教师账号已创建", en: "Teacher account created" }),
      )
      setCreateOpen(false)
      setForm({ email: "", full_name: null, password: "" })
      void invalidate()
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const toggleMutation = useMutation({
    mutationFn: (p: { id: string; is_active: boolean }) =>
      SchoolService.updateMember({
        user_id: p.id,
        memberUpdate: { is_active: p.is_active },
      }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "状态已更新", en: "Status updated" }))
      setPendingToggle(null)
      void invalidate()
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const resetMutation = useMutation({
    mutationFn: (p: { id: string; password: string }) =>
      SchoolService.updateMember({
        user_id: p.id,
        memberUpdate: { password: p.password },
      }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "密码已重置", en: "Password reset" }))
      setResetTarget(null)
      setNewPassword("")
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle className="flex items-center gap-2 text-xl">
              <UserRoundCog className="size-5" aria-hidden="true" />
              {t({ zh: "教师管理", en: "Teacher Accounts" })}
            </CardTitle>
            <CardDescription>
              {t({
                zh: "本校教师账号的创建、停用与密码重置；学生账号请在「我的课堂」内导入",
                en: "Create, pause and reset passwords for your school's teachers; students are managed in classrooms",
              })}
            </CardDescription>
          </div>
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 size-4" aria-hidden="true" />
            {t({ zh: "新建教师", en: "New teacher" })}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Input
          aria-label={t({ zh: "搜索教师", en: "Search teachers" })}
          placeholder={t({ zh: "搜索邮箱 / 姓名", en: "Search email or name" })}
          className="max-w-sm"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {isPending ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t({ zh: "邮箱", en: "Email" })}</TableHead>
                  <TableHead>{t({ zh: "姓名", en: "Name" })}</TableHead>
                  <TableHead>{t({ zh: "角色", en: "Role" })}</TableHead>
                  <TableHead>{t({ zh: "状态", en: "Status" })}</TableHead>
                  <TableHead className="text-right">
                    {t({ zh: "操作", en: "Actions" })}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data?.data ?? []).map((m) => (
                  <TableRow key={m.id}>
                    <TableCell className="font-mono text-xs">
                      {m.email}
                    </TableCell>
                    <TableCell>{m.full_name ?? "—"}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          m.role === "school_admin" ? "default" : "secondary"
                        }
                      >
                        {m.role === "school_admin"
                          ? t({ zh: "管理员", en: "Admin" })
                          : t({ zh: "教师", en: "Teacher" })}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={m.is_active ? "outline" : "destructive"}>
                        {m.is_active
                          ? t({ zh: "在用", en: "Active" })
                          : t({ zh: "已停用", en: "Paused" })}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setResetTarget({ id: m.id, name: m.email ?? "" })
                          }
                        >
                          {t({ zh: "重置密码", en: "Reset password" })}
                        </Button>
                        {m.is_active && m.role !== "school_admin" ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              setPendingToggle({
                                id: m.id,
                                active: m.is_active ?? true,
                                name: m.email ?? "",
                              })
                            }
                          >
                            {t({ zh: "停用", en: "Pause" })}
                          </Button>
                        ) : null}
                        {!m.is_active ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              toggleMutation.mutate({
                                id: m.id,
                                is_active: true,
                              })
                            }
                          >
                            {t({ zh: "恢复", en: "Resume" })}
                          </Button>
                        ) : null}
                      </div>
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
            <DialogTitle>
              {t({ zh: "新建教师账号", en: "New teacher" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "账号自动归属本校；初始密码请当面或安全渠道转交",
                en: "The account belongs to your school; hand over the password securely",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <Label htmlFor="m-email">
                {t({ zh: "邮箱", en: "Email" })}{" "}
                <span className="text-destructive">*</span>
              </Label>
              <Input
                id="m-email"
                type="email"
                className="min-h-11 text-base"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="m-name">{t({ zh: "姓名", en: "Name" })}</Label>
              <Input
                id="m-name"
                className="min-h-11 text-base"
                value={form.full_name ?? ""}
                onChange={(e) =>
                  setForm({ ...form, full_name: e.target.value || null })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="m-pw">
                {t({ zh: "初始密码", en: "Initial password" })}{" "}
                <span className="text-destructive">*</span>
              </Label>
              <Input
                id="m-pw"
                type="text"
                className="min-h-11 text-base"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <LoadingButton
              className="w-full sm:w-auto"
              loading={createMutation.isPending}
              disabled={!form.email || form.password.length < 8}
              onClick={() => createMutation.mutate(form)}
            >
              {t({ zh: "创建", en: "Create" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={resetTarget !== null}
        onOpenChange={(o) => !o && setResetTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "重置密码", en: "Reset password" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: `为 ${resetTarget?.name ?? ""} 设置新密码（原密码立即失效，已登录会话将在下次请求时登出）`,
                en: `Set a new password for ${resetTarget?.name ?? ""}; existing sessions are logged out on next request`,
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2 py-2">
            <Label htmlFor="m-newpw">
              {t({ zh: "新密码", en: "New password" })}
            </Label>
            <Input
              id="m-newpw"
              type="text"
              className="min-h-11 text-base"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </div>
          <DialogFooter>
            <LoadingButton
              className="w-full sm:w-auto"
              loading={resetMutation.isPending}
              disabled={newPassword.length < 8}
              onClick={() =>
                resetTarget &&
                resetMutation.mutate({
                  id: resetTarget.id,
                  password: newPassword,
                })
              }
            >
              {t({ zh: "确认重置", en: "Reset" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={pendingToggle !== null}
        title={t({ zh: "停用账号", en: "Pause account" })}
        description={t({
          zh: `停用后「${pendingToggle?.name ?? ""}」将无法登录（数据保留）`,
          en: `"${pendingToggle?.name ?? ""}" cannot sign in again; data is kept`,
        })}
        confirmText={t({ zh: "确认停用", en: "Pause" })}
        onOpenChange={(o) => !o && setPendingToggle(null)}
        onConfirm={() => {
          if (pendingToggle) {
            toggleMutation.mutate({ id: pendingToggle.id, is_active: false })
          }
        }}
      />
    </Card>
  )
}

export const Route = createFileRoute("/_layout/school/members")({
  component: SchoolMembersPage,
})
