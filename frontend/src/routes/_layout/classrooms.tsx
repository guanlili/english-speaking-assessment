import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ClipboardPaste, Copy, Plus, RotateCcw, UserMinus } from "lucide-react"
import { useMemo, useState } from "react"
import {
  ClassesService,
  type StudentImportResult,
  type StudentsBulkResetPasswordsResponse,
  StudentsService,
} from "@/client"

type StudentBulkResetResult = StudentsBulkResetPasswordsResponse

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
import { Textarea } from "@/components/ui/textarea"
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"

export const Route = createFileRoute("/_layout/classrooms")({
  component: MyClassroomsPage,
  head: () => ({ meta: [{ title: `我的课堂 - ${APP_NAME}` }] }),
})

function MyClassroomsPage() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const classroomsQuery = useQuery({
    queryKey: ["my-classrooms"],
    queryFn: () => ClassesService.listMyClassrooms(),
  })

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: ["my-classrooms"] })

  // ── 新建课堂 ──
  const [createOpen, setCreateOpen] = useState(false)
  const [keyword, setKeyword] = useState("")
  const [classSize, setClassSize] = useState(40)
  const createMutation = useMutation({
    mutationFn: () =>
      ClassesService.createClass({ requestBody: { class_size: classSize } }),
    onSuccess: (data) => {
      showSuccessToast(`课堂已创建，课堂码 ${data.code}`)
      setCreateOpen(false)
      invalidate()
    },
    onError: (error) => showErrorToast(`创建失败：${error.message}`),
  })

  const classrooms = classroomsQuery.data ?? []

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-semibold tracking-widest text-primary">
            从这里开始上课
          </p>
          <h1 className="text-3xl font-bold tracking-tight">我的课堂</h1>
          <p className="text-muted-foreground">
            一间课堂，一个教学空间。安排口语练习，查看学生录音与参考反馈。
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus />
          新建课堂
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {[
          { title: "课前 · 准备题目", text: "文章朗读、听句复述、模拟问答" },
          { title: "课中 · 安排练习", text: "进入课堂，选择内容并预览发布" },
          { title: "课后 · 查看结果", text: "听录音、看参考反馈、跟踪进步" },
        ].map((step, index) => (
          <div
            key={step.title}
            className="flex gap-3 rounded-xl border bg-card p-5"
          >
            <span className="text-sm font-semibold text-primary">
              0{index + 1}
            </span>
            <div>
              <p className="text-sm font-semibold">{step.title}</p>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                {step.text}
              </p>
            </div>
          </div>
        ))}
      </div>
      <Input
        aria-label="搜索课堂码"
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
        placeholder="搜索课堂码…"
        className="max-w-sm"
      />
      <Card>
        <CardHeader>
          <CardTitle className="text-base">课堂列表</CardTitle>
          <CardDescription>
            {classrooms.length} 间课堂 ·
            进入课堂安排练习，学生管理在各课堂卡片中。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {classroomsQuery.isPending ? (
            <div className="flex flex-col gap-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : classroomsQuery.isError ? (
            <div className="flex flex-col items-center gap-3 py-8 text-muted-foreground">
              <p>课堂列表加载失败。</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void classroomsQuery.refetch()}
              >
                重试
              </Button>
            </div>
          ) : classrooms.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              还没有课堂，点「新建课堂」开始：课堂码会发给学生配合学号账号使用。
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {classrooms
                .filter((classroom) =>
                  classroom.code
                    .toLowerCase()
                    .includes(keyword.trim().toLowerCase()),
                )
                .map((c) => (
                  <ClassroomCard
                    key={c.id}
                    classroom={c}
                    onInvalidated={invalidate}
                  />
                ))}
            </div>
          )}
        </CardContent>
      </Card>

      {classrooms.length > 0 &&
        !classrooms.some((classroom) =>
          classroom.code.toLowerCase().includes(keyword.trim().toLowerCase()),
        ) && (
          <p className="py-6 text-center text-muted-foreground">
            没有匹配的课堂。
          </p>
        )}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建课堂</DialogTitle>
            <DialogDescription>
              创建后生成课堂码；学生用学号账号登录后输入课堂码加入。
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="class-size">班级人数上限</Label>
              <Input
                id="class-size"
                type="number"
                min={1}
                max={100}
                value={classSize}
                onChange={(e) => setClassSize(Number(e.target.value))}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <LoadingButton
              loading={createMutation.isPending}
              disabled={
                !Number.isInteger(classSize) || classSize < 1 || classSize > 100
              }
              onClick={() => createMutation.mutate()}
            >
              创建
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function ClassroomCard({
  classroom,
  onInvalidated,
}: {
  classroom: {
    id: string
    code: string
    is_active: boolean
    class_size: number
  }
  onInvalidated: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [importOpen, setImportOpen] = useState(false)
  const [rosterOpen, setRosterOpen] = useState(false)

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(classroom.code)
      showSuccessToast(`课堂码 ${classroom.code} 已复制`)
    } catch {
      showErrorToast(`复制失败，请手动复制课堂码 ${classroom.code}`)
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="font-mono text-lg">{classroom.code}</CardTitle>
          <CardDescription>
            上限 {classroom.class_size} 人
            {classroom.is_active === false && " · 已停用"}
          </CardDescription>
        </div>
        <Badge variant={classroom.is_active ? "outline" : "secondary"}>
          {classroom.is_active ? "可使用" : "已停用"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          安排本次练习，查看学生作答与录音。
        </p>
        <div className="flex flex-wrap gap-2">
          {classroom.is_active ? (
            <Button asChild>
              <Link to="/t/$code" params={{ code: classroom.code }}>
                进入课堂 →
              </Link>
            </Button>
          ) : (
            <Button disabled>课堂已停用</Button>
          )}
          <Button variant="outline" onClick={() => void copyCode()}>
            <Copy className="size-3.5" />
            复制课堂码
          </Button>
        </div>
        <details className="border-t pt-3">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            学生管理 · 名单与账号
          </summary>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setImportOpen(true)}
            >
              <ClipboardPaste className="size-3.5" />
              导入学生
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRosterOpen(true)}
            >
              学生名单
            </Button>
          </div>
        </details>
      </CardContent>
      <StudentImportDialog
        classroomId={classroom.id}
        classroomCode={classroom.code}
        open={importOpen}
        onOpenChange={setImportOpen}
        onDone={onInvalidated}
      />
      <StudentRosterDialog
        classroomId={classroom.id}
        open={rosterOpen}
        onOpenChange={setRosterOpen}
      />
    </Card>
  )
}

function StudentImportDialog({
  classroomId,
  classroomCode,
  open,
  onOpenChange,
  onDone,
}: {
  classroomId: string
  classroomCode: string
  open: boolean
  onOpenChange: (v: boolean) => void
  onDone: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [text, setText] = useState("")
  const [result, setResult] = useState<StudentImportResult | null>(null)

  const lines = useMemo(
    () =>
      text
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean)
        .map((l) => {
          const [username, ...rest] = l.split(/\s+/)
          return {
            username: username ?? "",
            full_name: rest.join(" ") || username,
          }
        }),
    [text],
  )

  const mutation = useMutation({
    mutationFn: () =>
      StudentsService.importStudents({
        requestBody: { classroom_id: classroomId, lines },
      }),
    onSuccess: (res) => {
      setResult(res)
      if (res.created + res.merged > 0) {
        showSuccessToast(
          `导入完成：新建 ${res.created}、绑定历史档案 ${res.merged}${
            res.skipped ? `、跳过 ${res.skipped}` : ""
          }`,
        )
        onDone()
      } else {
        showErrorToast("没有导入任何学生，请检查名单")
      }
    },
    onError: (error) => showErrorToast(`导入失败：${error.message}`),
  })

  const exportCsv = () => {
    if (!result) return
    const rows = [
      ["学号", "姓名", "初始密码", "是否绑定历史档案"],
      ...result.rows.map((r) => [
        r.username,
        r.full_name,
        r.initial_password ?? "",
        r.merged_existing ? "是" : "否",
      ]),
    ]
    const csv = rows.map((r) => r.join(",")).join("\n")
    const url = URL.createObjectURL(
      new Blob([`\ufeff${csv}`], { type: "text/csv" }),
    )
    const a = document.createElement("a")
    a.href = url
    a.download = `学生初始密码-${classroomCode}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) {
          setText("")
          setResult(null)
        }
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>导入学生（{classroomCode}）</DialogTitle>
          <DialogDescription>
            每行「学号 姓名」（空格或制表符分隔）；系统生成初始密码，
            与历史匿名学生同名时自动绑定其练习数据。初始密码仅显示一次，请导出保存。
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <Textarea
            rows={8}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"2026001 李雷\n2026002 韩梅梅\n2026003 林涛"}
            aria-label="学生名单"
          />
          <div className="text-sm text-muted-foreground">
            将导入{" "}
            <span className="font-medium text-foreground">{lines.length}</span>{" "}
            名学生
          </div>
          {result && (
            <div className="rounded-md border bg-muted/40 p-3 text-sm">
              <p>
                新建 {result.created} · 绑定历史 {result.merged} · 跳过{" "}
                {result.skipped}
              </p>
              {result.rows.some((r) => r.error) && (
                <ul className="mt-2 list-inside list-disc text-destructive">
                  {result.rows
                    .filter((r) => r.error)
                    .map((r) => (
                      <li key={r.username}>
                        {r.username}：{r.error}
                      </li>
                    ))}
                </ul>
              )}
            </div>
          )}
        </div>
        <DialogFooter className="flex-row gap-2">
          {result && (
            <Button variant="outline" onClick={exportCsv}>
              导出初始密码 CSV
            </Button>
          )}
          <LoadingButton
            disabled={lines.length === 0}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            导入
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function StudentRosterDialog({
  classroomId,
  open,
  onOpenChange,
}: {
  classroomId: string
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const rosterQuery = useQuery({
    queryKey: ["students", classroomId],
    queryFn: () => StudentsService.listStudents({ classroomId }),
    enabled: open,
  })
  const [resetResult, setResetResult] = useState<string | null>(null)
  const [resetPwd, setResetPwd] = useState<string | null>(null)
  const [bulkResult, setBulkResult] = useState<StudentBulkResetResult | null>(
    null,
  )
  const [bulkConfirm, setBulkConfirm] = useState(false)

  const resetMutation = useMutation({
    mutationFn: (studentId: string) =>
      StudentsService.resetStudentPassword({ studentId }),
    onSuccess: (data) => {
      setResetResult(data.new_password)
      showSuccessToast("已重置，请把新密码发给学生")
    },
    onError: (error) => showErrorToast(`重置失败：${error.message}`),
  })

  const bulkResetMutation = useMutation({
    mutationFn: () => StudentsService.bulkResetPasswords({ classroomId }),
    onSuccess: (res) => {
      setBulkResult(res)
      showSuccessToast(`已重置 ${res.reset} 个账号，请导出新密码`)
    },
    onError: (error) => showErrorToast(`批量重置失败：${error.message}`),
  })

  const exportBulkCsv = () => {
    if (!bulkResult) return
    const rows = [
      ["学号", "姓名", "新初始密码"],
      ...bulkResult.rows.map((r) => [
        r.username,
        r.full_name ?? "",
        r.new_password,
      ]),
    ]
    const csv = rows.map((r) => r.join(",")).join("\n")
    const url = URL.createObjectURL(
      new Blob([`\ufeff${csv}`], { type: "text/csv" }),
    )
    const a = document.createElement("a")
    a.href = url
    a.download = `学生新初始密码-${classroomId.slice(0, 8)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const removeMutation = useMutation({
    mutationFn: (studentId: string) =>
      StudentsService.removeStudent({ studentId }),
    onSuccess: () => {
      showSuccessToast("已移出课堂（档案与历史保留）")
      setResetPwd(null)
      void rosterQuery.refetch()
    },
    onError: (error) => showErrorToast(`移出失败：${error.message}`),
  })

  const students = rosterQuery.data ?? []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>学生名单</DialogTitle>
          <DialogDescription>
            学号账号与改密状态；重置密码生成新初始密码（仅显示一次）。
          </DialogDescription>
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              初始密码 CSV 丢了？可全部重置后重新导出（旧密码立即失效）。
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setBulkConfirm(true)}
            >
              全部重置并导出
            </Button>
          </div>
          {bulkResult && (
            <div className="rounded-md border bg-muted/40 p-3 text-sm">
              已重置 {bulkResult.reset} 个账号。
              <Button
                variant="outline"
                size="sm"
                className="ml-2"
                onClick={exportBulkCsv}
              >
                导出新密码 CSV
              </Button>
            </div>
          )}
        </DialogHeader>
        {resetResult && (
          <div className="rounded-md border bg-muted/40 p-3 text-sm">
            新初始密码：
            <span className="font-mono font-semibold">{resetResult}</span>
            （仅显示一次，请立即转告学生）
          </div>
        )}
        {rosterQuery.isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : students.length === 0 ? (
          <p className="py-6 text-center text-muted-foreground">
            还没有学生账号，先「导入学生」。
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>姓名</TableHead>
                <TableHead>学号</TableHead>
                <TableHead>状态</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {students.map((s) => (
                <TableRow key={s.student.id}>
                  <TableCell className="font-medium">
                    {s.student.display_name}
                  </TableCell>
                  <TableCell className="font-mono">
                    {s.username ?? "—"}
                  </TableCell>
                  <TableCell>
                    {s.username ? (
                      s.must_change_password ? (
                        <Badge variant="secondary">待改密</Badge>
                      ) : (
                        <Badge variant="outline">正常</Badge>
                      )
                    ) : (
                      <Badge variant="secondary">未绑账号</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {s.username && (
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label="重置密码"
                          onClick={() => {
                            setResetResult(null)
                            setResetPwd(s.student.id)
                            resetMutation.mutate(s.student.id)
                          }}
                        >
                          <RotateCcw className="size-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label="移出课堂"
                          onClick={() => setResetPwd(s.student.id)}
                        >
                          <UserMinus className="size-3.5 text-destructive" />
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DialogContent>
      <ConfirmDialog
        open={resetPwd !== null && resetResult === null}
        title="把该学生移出课堂？"
        description="仅解除账号与课堂的绑定；练习档案与作答历史保留，重新导入相同学号可找回。"
        confirmText="移出课堂"
        onOpenChange={(next) => {
          if (!next) setResetPwd(null)
        }}
        onConfirm={async () => {
          if (resetPwd) await removeMutation.mutateAsync(resetPwd)
        }}
      />

      <Dialog open={bulkConfirm} onOpenChange={setBulkConfirm}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>重置全部学生密码？</DialogTitle>
            <DialogDescription>
              课堂内全部已绑定账号的密码将立即失效，生成新初始密码（学生下次登录需改密）。确定继续？
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkConfirm(false)}>
              取消
            </Button>
            <LoadingButton
              loading={bulkResetMutation.isPending}
              onClick={() => {
                bulkResetMutation.mutate()
                setBulkConfirm(false)
              }}
            >
              重置全部
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Dialog>
  )
}
