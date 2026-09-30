import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { AdminService, ClassesService, UsersService } from "@/client"
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
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"

export const Route = createFileRoute("/_layout/admin/classrooms")({
  component: ClassroomsAdmin,
  head: () => ({
    meta: [{ title: `课堂码 / Classroom Codes - ${APP_NAME}` }],
  }),
})

const UNBIND = "__unbind__"

function ClassroomsAdmin() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [toDeactivate, setToDeactivate] = useState<{
    id: string
    code: string
  } | null>(null)

  const listQuery = useQuery({
    queryKey: ["admin", "classrooms"],
    queryFn: () => AdminService.listClassrooms(),
  })
  // 授权教师从账号列表里选（教师 = 独立登录账号，课堂只做范围绑定）
  const usersQuery = useQuery({
    queryKey: ["admin", "teachers"],
    queryFn: () => UsersService.readUsers({ limit: 200 }),
  })

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: ["admin", "classrooms"] })

  const createMutation = useMutation({
    mutationFn: () =>
      ClassesService.createClass({ requestBody: { class_size: 40 } }),
    onSuccess: (data) => {
      showSuccessToast(
        t({
          zh: `课堂码已生成：${data.code}`,
          en: `Classroom code generated: ${data.code}`,
        }),
      )
      invalidate()
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `生成失败：${error.message}`,
          en: `Generate failed: ${error.message}`,
        }),
      ),
  })

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: string
      patch: {
        unlock_all?: boolean
        owner_id?: string | null
        is_active?: boolean
      }
    }) => AdminService.updateClassroom({ classroomId: id, requestBody: patch }),
    onSuccess: (_data, vars) => {
      if ("owner_id" in vars.patch) {
        showSuccessToast(
          vars.patch.owner_id
            ? t({ zh: "已绑定授权教师", en: "Teacher bound" })
            : t({ zh: "已解绑授权教师", en: "Teacher unbound" }),
        )
      } else if (vars.patch.is_active === true) {
        showSuccessToast(
          t({ zh: "课堂已恢复启用", en: "Classroom re-enabled" }),
        )
      } else if (typeof vars.patch.unlock_all === "boolean") {
        showSuccessToast(
          vars.patch.unlock_all
            ? t({ zh: "已开启一键全开", en: "Unlock-all enabled" })
            : t({ zh: "已恢复顺序解锁", en: "Sequential unlock restored" }),
        )
      }
      invalidate()
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `操作失败：${error.message}`,
          en: `Operation failed: ${error.message}`,
        }),
      ),
  })

  const deactivateMutation = useMutation({
    mutationFn: (id: string) =>
      AdminService.deactivateClassroom({ classroomId: id }),
    onSuccess: () => {
      showSuccessToast(
        t({
          zh: "已停用：学生与老师访问都会被拒绝",
          en: "Disabled: both students and teachers are denied access",
        }),
      )
      setToDeactivate(null)
      invalidate()
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `停用失败：${error.message}`,
          en: `Disable failed: ${error.message}`,
        }),
      ),
  })

  const classrooms = listQuery.data ?? []
  const teachers = (usersQuery.data?.data ?? []).filter((u) => u.is_active)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t({ zh: "课堂码", en: "Classroom Codes" })}
        </h1>
        <p className="text-muted-foreground">
          {t({
            zh: "邀请学生加入课堂，并从教师面板安排今日练习。",
            en: "Invite students into a classroom and schedule Today's Practice from the teacher panel.",
          })}
        </p>
      </div>

      <Button
        className="w-fit"
        onClick={() => createMutation.mutate()}
        disabled={createMutation.isPending}
      >
        <Plus />
        {t({
          zh: "生成新课堂码（默认班额 40）",
          en: "Generate New Code (default size 40)",
        })}
      </Button>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "全部课堂", en: "All Classrooms" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "按创建时间排序；授权教师决定谁能看到这个班的名单和录音。",
              en: "Sorted by creation time; the authorized teacher controls who can see this class's roster and recordings.",
            })}
            <span className="mt-1 block sm:hidden">
              {t({
                zh: "横向滑动表格，可以查看完整内容。",
                en: "Swipe the table sideways to see everything.",
              })}
            </span>
          </CardDescription>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {t({
              zh: "解锁方式：顺序解锁 = 学生按单元顺序逐个推进（今日练习始终练当前单元）； 一键全开 = 所有单元在主题探索中立即可练。勾选即切换。",
              en: "Unlock modes: Sequential = students progress unit by unit (Today's Practice always uses the current unit); Unlock-all = every unit becomes immediately available in topic exploration. Tick to switch.",
            })}
          </p>
        </CardHeader>
        <CardContent>
          {listQuery.isPending ? (
            <div className="flex flex-col gap-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : listQuery.isError ? (
            <div className="flex flex-col items-center gap-3 py-8 text-muted-foreground">
              <p>
                {t({
                  zh: "课堂列表加载失败。",
                  en: "Failed to load classrooms.",
                })}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void listQuery.refetch()}
              >
                {t({ zh: "重试", en: "Retry" })}
              </Button>
            </div>
          ) : classrooms.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              {t({
                zh: "还没有课堂，点上面的按钮生成第一个课堂码。",
                en: "No classrooms yet — generate the first code with the button above.",
              })}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t({ zh: "课堂", en: "Classroom" })}</TableHead>
                  <TableHead>{t({ zh: "班额", en: "Size" })}</TableHead>
                  <TableHead>
                    {t({ zh: "授权教师", en: "Authorized Teacher" })}
                  </TableHead>
                  <TableHead>
                    {t({ zh: "解锁方式", en: "Unlock Mode" })}
                  </TableHead>
                  <TableHead>{t({ zh: "状态", en: "Status" })}</TableHead>
                  <TableHead>
                    {t({ zh: "课堂入口", en: "Entry Links" })}
                  </TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {classrooms.map((c) => {
                  const owner = teachers.find((t) => t.id === c.owner_id)
                  return (
                    <TableRow key={c.id}>
                      <TableCell>
                        <p className="font-medium">{c.name}</p>
                        <p className="font-mono text-xs text-muted-foreground">
                          {c.code}
                        </p>
                      </TableCell>
                      <TableCell>{c.class_size}</TableCell>
                      <TableCell>
                        <div className="flex min-w-48 items-center gap-2">
                          <Select
                            value={c.owner_id ?? UNBIND}
                            onValueChange={(next) =>
                              updateMutation.mutate({
                                id: c.id,
                                patch: {
                                  owner_id: next === UNBIND ? null : next,
                                },
                              })
                            }
                          >
                            <SelectTrigger className="h-8 w-40 text-xs">
                              <SelectValue
                                placeholder={
                                  owner
                                    ? owner.email
                                    : t({ zh: "未绑定", en: "Unassigned" })
                                }
                              />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={UNBIND}>
                                {t({ zh: "未绑定", en: "Unassigned" })}
                              </SelectItem>
                              {teachers.map((t) => (
                                <SelectItem key={t.id} value={t.id}>
                                  {t.email}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          {owner ? (
                            <Badge variant="outline">
                              {t({ zh: "已绑定", en: "Bound" })}
                            </Badge>
                          ) : (
                            <Badge variant="secondary">
                              {t({ zh: "无授权教师", en: "No Teacher" })}
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <label
                          htmlFor={`unlock-all-${c.code}`}
                          className="flex min-h-9 cursor-pointer items-center gap-2 text-sm"
                        >
                          <Checkbox
                            id={`unlock-all-${c.code}`}
                            aria-label={t({
                              zh: `课堂 ${c.code}：一键全开`,
                              en: `Classroom ${c.code}: unlock all`,
                            })}
                            checked={c.unlock_all ?? false}
                            onCheckedChange={(checked) =>
                              updateMutation.mutate({
                                id: c.id,
                                patch: { unlock_all: checked === true },
                              })
                            }
                          />
                          {(c.unlock_all ?? false)
                            ? t({ zh: "一键全开", en: "Unlock All" })
                            : t({ zh: "顺序解锁", en: "Sequential" })}
                        </label>
                      </TableCell>
                      <TableCell>
                        {c.is_active ? (
                          <Badge variant="outline">
                            {t({ zh: "启用", en: "Enabled" })}
                          </Badge>
                        ) : (
                          <Badge variant="secondary">
                            {t({ zh: "已停用", en: "Disabled" })}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-2">
                          <Button asChild variant="outline" size="sm">
                            <Link to="/j/$code" params={{ code: c.code }}>
                              {t({ zh: "学生入口", en: "Student Entry" })}
                            </Link>
                          </Button>
                          <Button asChild variant="secondary" size="sm">
                            <Link to="/t/$code" params={{ code: c.code }}>
                              {t({ zh: "教师面板", en: "Teacher Panel" })}
                            </Link>
                          </Button>
                        </div>
                      </TableCell>
                      <TableCell>
                        {c.is_active ? (
                          <Button
                            variant="ghost"
                            aria-label={t({
                              zh: `停用课堂 ${c.code}`,
                              en: `Disable classroom ${c.code}`,
                            })}
                            size="icon-sm"
                            onClick={() =>
                              setToDeactivate({ id: c.id, code: c.code })
                            }
                          >
                            <Trash2 className="text-destructive" />
                          </Button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              updateMutation.mutate({
                                id: c.id,
                                patch: { is_active: true },
                              })
                            }
                          >
                            {t({ zh: "恢复启用", en: "Re-enable" })}
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={toDeactivate !== null}
        title={t({
          zh: `停用课堂 ${toDeactivate?.code ?? ""}？`,
          en: `Disable classroom ${toDeactivate?.code ?? ""}?`,
        })}
        description={t({
          zh: "停用后学生无法加入或继续练习，教师面板也会拒绝访问；数据保留，可随时恢复启用。",
          en: "Students can no longer join or keep practicing, and the teacher panel denies access; data is kept and it can be re-enabled anytime.",
        })}
        confirmText={t({ zh: "停用课堂", en: "Disable Classroom" })}
        onOpenChange={(next) => {
          if (!next) setToDeactivate(null)
        }}
        onConfirm={async () => {
          if (toDeactivate) {
            await deactivateMutation.mutateAsync(toDeactivate.id)
          }
        }}
      />
    </div>
  )
}
