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

export const Route = createFileRoute("/_layout/admin/classrooms")({
  component: ClassroomsAdmin,
  head: () => ({ meta: [{ title: `课堂码 - ${APP_NAME}` }] }),
})

const UNBIND = "__unbind__"

function ClassroomsAdmin() {
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
      showSuccessToast(`课堂码已生成：${data.code}`)
      invalidate()
    },
    onError: (error) => showErrorToast(`生成失败：${error.message}`),
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
          vars.patch.owner_id ? "已绑定授权教师" : "已解绑授权教师",
        )
      } else if (vars.patch.is_active === true) {
        showSuccessToast("课堂已恢复启用")
      } else if (typeof vars.patch.unlock_all === "boolean") {
        showSuccessToast(
          vars.patch.unlock_all ? "已开启一键全开" : "已恢复顺序解锁",
        )
      }
      invalidate()
    },
    onError: (error) => showErrorToast(`操作失败：${error.message}`),
  })

  const deactivateMutation = useMutation({
    mutationFn: (id: string) =>
      AdminService.deactivateClassroom({ classroomId: id }),
    onSuccess: () => {
      showSuccessToast("已停用：学生与老师访问都会被拒绝")
      setToDeactivate(null)
      invalidate()
    },
    onError: (error) => showErrorToast(`停用失败：${error.message}`),
  })

  const classrooms = listQuery.data ?? []
  const teachers = (usersQuery.data?.data ?? []).filter((u) => u.is_active)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">课堂码</h1>
        <p className="text-muted-foreground">
          邀请学生加入课堂，并从教师面板安排今日练习。
        </p>
      </div>

      <Button
        className="w-fit"
        onClick={() => createMutation.mutate()}
        disabled={createMutation.isPending}
      >
        <Plus />
        生成新课堂码（默认班额 40）
      </Button>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">全部课堂</CardTitle>
          <CardDescription>
            按创建时间排序；授权教师决定谁能看到这个班的名单和录音。
          </CardDescription>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            解锁方式：顺序解锁 =
            学生按单元顺序逐个推进（今日练习始终练当前单元）； 一键全开 =
            所有单元在主题探索中立即可练。勾选即切换。
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
              <p>课堂列表加载失败。</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void listQuery.refetch()}
              >
                重试
              </Button>
            </div>
          ) : classrooms.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              还没有课堂，点上面的按钮生成第一个课堂码。
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>课堂码</TableHead>
                  <TableHead>班额</TableHead>
                  <TableHead>授权教师</TableHead>
                  <TableHead>解锁方式</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>课堂入口</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {classrooms.map((c) => {
                  const owner = teachers.find((t) => t.id === c.owner_id)
                  return (
                    <TableRow key={c.id}>
                      <TableCell className="font-mono font-medium">
                        {c.code}
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
                                placeholder={owner ? owner.email : "未绑定"}
                              />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={UNBIND}>未绑定</SelectItem>
                              {teachers.map((t) => (
                                <SelectItem key={t.id} value={t.id}>
                                  {t.email}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          {owner ? (
                            <Badge variant="outline">已绑定</Badge>
                          ) : (
                            <Badge variant="secondary">无授权教师</Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2 text-sm">
                          <Checkbox
                            aria-label={`课堂 ${c.code}：一键全开`}
                            checked={c.unlock_all ?? false}
                            onCheckedChange={(checked) =>
                              updateMutation.mutate({
                                id: c.id,
                                patch: { unlock_all: checked === true },
                              })
                            }
                          />
                          {(c.unlock_all ?? false) ? "一键全开" : "顺序解锁"}
                        </div>
                      </TableCell>
                      <TableCell>
                        {c.is_active ? (
                          <Badge variant="outline">启用</Badge>
                        ) : (
                          <Badge variant="secondary">已停用</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-2">
                          <Button asChild variant="outline" size="sm">
                            <Link to="/j/$code" params={{ code: c.code }}>
                              学生入口
                            </Link>
                          </Button>
                          <Button asChild variant="secondary" size="sm">
                            <Link to="/t/$code" params={{ code: c.code }}>
                              教师面板
                            </Link>
                          </Button>
                        </div>
                      </TableCell>
                      <TableCell>
                        {c.is_active ? (
                          <Button
                            variant="ghost"
                            aria-label={`停用课堂 ${c.code}`}
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
                            恢复启用
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
        title={`停用课堂 ${toDeactivate?.code ?? ""}？`}
        description="停用后学生无法加入或继续练习，教师面板也会拒绝访问；数据保留，可随时恢复启用。"
        confirmText="停用课堂"
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
