import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, redirect } from "@tanstack/react-router"
import { Plus, Trash2 } from "lucide-react"
import { AdminService, ClassesService, UsersService } from "@/client"
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
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!user.is_superuser) {
      throw redirect({ to: "/" })
    }
  },
  head: () => ({ meta: [{ title: `课堂码 - ${APP_NAME}` }] }),
})

function ClassroomsAdmin() {
  const queryClient = useQueryClient()
  const { showSuccessToast } = useCustomToast()

  const listQuery = useQuery({
    queryKey: ["admin", "classrooms"],
    queryFn: () => AdminService.listClassrooms(),
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "classrooms"] })

  const createMutation = useMutation({
    mutationFn: () =>
      ClassesService.createClass({ requestBody: { class_size: 40 } }),
    onSuccess: (data) => {
      showSuccessToast(`课堂码已生成：${data.code}`)
      invalidate()
    },
  })

  const deactivateMutation = useMutation({
    mutationFn: (id: string) =>
      AdminService.deactivateClassroom({ classroomId: id }),
    onSuccess: () => {
      showSuccessToast("已停用")
      invalidate()
    },
  })

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
          <CardDescription>按创建时间排序</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>课堂码</TableHead>
                <TableHead>班额</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>课堂入口</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {(listQuery.data ?? []).map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-mono font-medium">
                    {c.code}
                  </TableCell>
                  <TableCell>{c.class_size}</TableCell>
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
                    {c.is_active && (
                      <Button
                        variant="ghost"
                        aria-label={`停用课堂 ${c.code}`}
                        size="icon-sm"
                        onClick={() => deactivateMutation.mutate(c.id)}
                      >
                        <Trash2 className="text-destructive" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
