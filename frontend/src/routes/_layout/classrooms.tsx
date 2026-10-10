import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ClipboardPaste, Copy, Plus, RotateCcw, UserMinus } from "lucide-react"
import { useMemo, useState } from "react"
import {
  ClassesService,
  type StudentImportResult,
  StudentsService,
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
import { NumberInput } from "@/components/ui/number-input"
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
import { copyText } from "@/lib/clipboard"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage, localizedDetail } from "@/utils"

export const Route = createFileRoute("/_layout/classrooms")({
  component: MyClassroomsPage,
  head: () => ({
    meta: [{ title: `我的课堂 / My Classrooms - ${APP_NAME}` }],
  }),
})

function MyClassroomsPage() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { t } = useI18n()
  const classroomsQuery = useQuery({
    queryKey: ["my-classrooms"],
    queryFn: () => ClassesService.listMyClassrooms(),
  })

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: ["my-classrooms"] })

  // ── 新建课堂 ──
  const [createOpen, setCreateOpen] = useState(false)
  const [keyword, setKeyword] = useState("")
  const [className, setClassName] = useState("")
  const [grade, setGrade] = useState("")
  const [teachingGoal, setTeachingGoal] = useState("")
  const [classSize, setClassSize] = useState(40)
  const createMutation = useMutation({
    mutationFn: () =>
      ClassesService.createClass({
        requestBody: {
          name: className.trim(),
          grade: grade.trim() || undefined,
          teaching_goal: teachingGoal.trim() || undefined,
          class_size: classSize,
        },
      }),
    onSuccess: (data) => {
      showSuccessToast(
        t({
          zh: `课堂已创建，课堂码 ${data.code}`,
          en: `Classroom created. Classroom code ${data.code}`,
        }),
      )
      setCreateOpen(false)
      setClassName("")
      setGrade("")
      setTeachingGoal("")
      invalidate()
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `创建失败：${error.message}`,
          en: `Failed to create: ${error.message}`,
        }),
      ),
  })

  const classrooms = classroomsQuery.data ?? []

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-semibold tracking-widest text-primary">
            {t({ zh: "从这里开始上课", en: "Start here" })}
          </p>
          <h1 className="text-3xl font-bold tracking-tight">
            {t({ zh: "我的课堂", en: "My Classrooms" })}
          </h1>
          <p className="text-muted-foreground">
            {t({
              zh: "一间课堂，一个教学空间。安排口语练习，查看学生录音与参考反馈。",
              en: "One classroom, one teaching space. Assign speaking practice and review student recordings with reference feedback.",
            })}
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus />
          {t({ zh: "新建课堂", en: "New Classroom" })}
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {[
          {
            title: {
              zh: "课前 · 准备题目",
              en: "Before class · Prepare questions",
            },
            text: {
              zh: "文章朗读、听句复述、情景问答",
              en: "Read Aloud, Listen & Repeat, Scenario Q&A",
            },
          },
          {
            title: {
              zh: "课中 · 安排练习",
              en: "In class · Assign practice",
            },
            text: {
              zh: "进入课堂，选择内容并预览发布",
              en: "Open the classroom, choose content and preview before publishing",
            },
          },
          {
            title: {
              zh: "课后 · 查看结果",
              en: "After class · Review results",
            },
            text: {
              zh: "听录音、看参考反馈、跟踪进步",
              en: "Listen to recordings, check reference feedback, track progress",
            },
          },
        ].map((step, index) => (
          <div
            key={step.title.zh}
            className="flex gap-3 rounded-xl border bg-card p-5"
          >
            <span className="text-sm font-semibold text-primary">
              0{index + 1}
            </span>
            <div>
              <p className="text-sm font-semibold">{t(step.title)}</p>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                {t(step.text)}
              </p>
            </div>
          </div>
        ))}
      </div>
      <Input
        aria-label={t({
          zh: "搜索课堂名称或课堂码",
          en: "Search by classroom name or code",
        })}
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
        placeholder={t({
          zh: "搜索课堂名称或课堂码…",
          en: "Search by classroom name or code…",
        })}
        className="max-w-sm"
      />
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "课堂列表", en: "Classroom List" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: `${classrooms.length} 间课堂 · 进入课堂安排练习，学生管理在各课堂卡片中。`,
              en: `${classrooms.length} classrooms · Open a classroom to assign practice; manage students in each classroom card.`,
            })}
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
              <p>
                {t({
                  zh: "课堂列表加载失败。",
                  en: "Failed to load classrooms.",
                })}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void classroomsQuery.refetch()}
              >
                {t({ zh: "重试", en: "Retry" })}
              </Button>
            </div>
          ) : classrooms.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              {t({
                zh: "还没有课堂，点「新建课堂」开始：课堂码会发给学生配合学号账号使用。",
                en: 'No classrooms yet — click "New Classroom" to start. The classroom code is given to students to use with their student ID accounts.',
              })}
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {classrooms
                .filter((classroom) =>
                  `${classroom.name ?? ""} ${classroom.code}`
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
          `${classroom.name ?? ""} ${classroom.code}`
            .toLowerCase()
            .includes(keyword.trim().toLowerCase()),
        ) && (
          <p className="py-6 text-center text-muted-foreground">
            {t({ zh: "没有匹配的课堂。", en: "No matching classrooms." })}
          </p>
        )}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "新建课堂", en: "New Classroom" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "创建后生成课堂码；学生用学号账号登录后输入课堂码加入。",
                en: "A classroom code is generated on creation; students sign in with their student ID account and join with the code.",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="class-name">
                {t({ zh: "课堂名称", en: "Classroom Name" })}
              </Label>
              <Input
                id="class-name"
                value={className}
                onChange={(e) => setClassName(e.target.value)}
                placeholder={t({
                  zh: "例如：六年级英语口语",
                  en: "e.g., Grade 6 English Speaking",
                })}
                maxLength={120}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor="class-grade">
                  {t({
                    zh: "年级 / 班型（可选）",
                    en: "Grade / Class (optional)",
                  })}
                </Label>
                <Input
                  id="class-grade"
                  value={grade}
                  onChange={(e) => setGrade(e.target.value)}
                  placeholder={t({
                    zh: "例如：六年级 2 班",
                    en: "e.g., Grade 6, Class 2",
                  })}
                  maxLength={64}
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="class-size">
                  {t({ zh: "班级人数上限", en: "Class Size Limit" })}
                </Label>
                <NumberInput
                  id="class-size"
                  min={1}
                  max={100}
                  value={classSize}
                  onValueChange={setClassSize}
                />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="teaching-goal">
                {t({
                  zh: "本阶段教学目标（可选）",
                  en: "Teaching Goal (optional)",
                })}
              </Label>
              <Textarea
                id="teaching-goal"
                value={teachingGoal}
                onChange={(e) => setTeachingGoal(e.target.value)}
                placeholder={t({
                  zh: "例如：能用完整句介绍自己的宠物",
                  en: "e.g., Can introduce their pet in full sentences",
                })}
                maxLength={255}
                rows={2}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <LoadingButton
              loading={createMutation.isPending}
              disabled={
                !className.trim() ||
                !Number.isInteger(classSize) ||
                classSize < 1 ||
                classSize > 100
              }
              onClick={() => createMutation.mutate()}
            >
              {t({ zh: "创建", en: "Create" })}
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
    name?: string | null
    grade?: string | null
    teaching_goal?: string | null
    is_active: boolean
    class_size: number
  }
  onInvalidated: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { t } = useI18n()
  const [importOpen, setImportOpen] = useState(false)
  const [rosterOpen, setRosterOpen] = useState(false)

  const copyCode = async () => {
    if (await copyText(classroom.code)) {
      showSuccessToast(
        t({
          zh: `课堂码 ${classroom.code} 已复制`,
          en: `Classroom code ${classroom.code} copied`,
        }),
      )
    } else {
      showErrorToast(
        t({
          zh: `复制失败，请手动复制课堂码 ${classroom.code}`,
          en: `Copy failed — please copy the classroom code ${classroom.code} manually`,
        }),
      )
    }
  }

  const [deleteOpen, setDeleteOpen] = useState(false)
  const deleteMutation = useMutation({
    mutationFn: () =>
      ClassesService.deleteClass({ code: classroom.code, deleteHistory: true }),
    onSuccess: () => {
      showSuccessToast(
        t({
          zh: `课堂 ${classroom.code} 已删除`,
          en: `Classroom ${classroom.code} deleted`,
        }),
      )
      setDeleteOpen(false)
      onInvalidated()
    },
    onError: (error) => showErrorToast(extractErrorMessage(error)),
  })

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="text-lg">
            {classroom.name ||
              t({ zh: "未命名课堂", en: "Untitled Classroom" })}
          </CardTitle>
          <CardDescription>
            <span className="font-mono">{classroom.code}</span>
            {classroom.grade && ` · ${classroom.grade}`}
            {t({
              zh: ` · 上限 ${classroom.class_size} 人`,
              en: ` · Limit ${classroom.class_size}`,
            })}
            {classroom.is_active === false &&
              t({ zh: " · 已停用", en: " · Deactivated" })}
          </CardDescription>
        </div>
        <Badge variant={classroom.is_active ? "outline" : "secondary"}>
          {classroom.is_active
            ? t({ zh: "可使用", en: "Active" })
            : t({ zh: "已停用", en: "Deactivated" })}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {classroom.teaching_goal ||
            t({
              zh: "安排本次练习，查看学生作答与录音。",
              en: "Assign practice and review student answers and recordings.",
            })}
        </p>
        <div className="flex flex-wrap gap-2">
          {classroom.is_active ? (
            <Button asChild>
              <Link to="/t/$code" params={{ code: classroom.code }}>
                {t({ zh: "进入课堂 →", en: "Open Classroom →" })}
              </Link>
            </Button>
          ) : (
            <Button disabled>
              {t({ zh: "课堂已停用", en: "Classroom deactivated" })}
            </Button>
          )}
          <Button variant="outline" onClick={() => void copyCode()}>
            <Copy className="size-3.5" />
            {t({ zh: "复制课堂码", en: "Copy Classroom Code" })}
          </Button>
        </div>
        <details className="border-t pt-3">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            {t({
              zh: "学生管理 · 名单与账号",
              en: "Students · Roster & Accounts",
            })}
          </summary>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setImportOpen(true)}
            >
              <ClipboardPaste className="size-3.5" />
              {t({ zh: "导入学生", en: "Import Students" })}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRosterOpen(true)}
            >
              {t({ zh: "学生名单", en: "Roster" })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => setDeleteOpen(true)}
            >
              {t({ zh: "删除课堂", en: "Delete Classroom" })}
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
      <ConfirmDialog
        open={deleteOpen}
        title={t({
          zh: `删除课堂 ${classroom.code}？`,
          en: `Delete classroom ${classroom.code}?`,
        })}
        description={t({
          zh: "确认后将永久删除该课堂、学生名单、发布记录及全部口语/词汇作答，包括已移出学生的历史。课堂码立即失效；学生账号和其他课堂的数据保留。正在评分时请等待评分结束再删除。",
          en: "Confirming permanently deletes this classroom, its roster, published assignments and all speaking/vocabulary answers, including history from removed students. The code stops working immediately. Student accounts and other classrooms are preserved. Wait for any scoring to finish before deleting.",
        })}
        confirmText={t({ zh: "删除课堂", en: "Delete Classroom" })}
        onOpenChange={(next) => {
          if (!next) setDeleteOpen(false)
        }}
        onConfirm={async () => {
          await deleteMutation.mutateAsync()
        }}
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
  const { t } = useI18n()
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
      const joined = res.joined ?? 0
      const already = res.already_enrolled ?? 0
      if (res.created + res.merged + joined > 0) {
        showSuccessToast(
          t({
            zh: `导入完成：新建 ${res.created}、绑定历史档案 ${res.merged}、加入本班 ${joined}${res.skipped ? `、跳过 ${res.skipped}` : ""}`,
            en: `Import done: ${res.created} created, ${res.merged} linked to existing profiles, ${joined} joined this class${res.skipped ? `, ${res.skipped} skipped` : ""}`,
          }),
        )
        onDone()
      } else if (already > 0 && res.skipped === 0) {
        showSuccessToast(
          t({
            zh: "名单内学生都已在班级中，无需改动",
            en: "Everyone on the roster is already in this class",
          }),
        )
        onDone()
      } else {
        showErrorToast(
          t({
            zh: "没有导入任何学生，请检查名单",
            en: "No students were imported; please check the roster",
          }),
        )
      }
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `导入失败：${error.message}`,
          en: `Import failed: ${error.message}`,
        }),
      ),
  })

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
          <DialogTitle>
            {t({
              zh: `导入学生（${classroomCode}）`,
              en: `Import Students (${classroomCode})`,
            })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "每行「学号 姓名」（空格或制表符分隔）；账号初始密码统一为默认密码 brs123456，与历史匿名学生同名时自动绑定其练习数据。学号已在其他班的：姓名一致即同一学生，将加入本班且不重置密码；姓名不一致会拒绝，请先核对名单。",
              en: 'One "Student ID Name" per line (separated by spaces or tabs). Accounts start with the default password brs123456, and names matching past anonymous students are automatically linked to their practice data. If a student ID already exists in another class with the same name, the student joins this class and their password is untouched; mismatched names are rejected — double-check the roster first.',
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <Textarea
            rows={8}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t({
              zh: "2026001 李雷\n2026002 韩梅梅\n2026003 林涛",
              en: "2026001 Li Lei\n2026002 Han Meimei\n2026003 Lin Tao",
            })}
            aria-label={t({ zh: "学生名单", en: "Student roster" })}
          />
          <div className="text-sm text-muted-foreground">
            {t({ zh: "将导入", en: "Importing" })}{" "}
            <span className="font-medium text-foreground">{lines.length}</span>{" "}
            {t({ zh: "名学生", en: "student(s)" })}
          </div>
          {result && (
            <div className="rounded-md border bg-muted/40 p-3 text-sm">
              <p>
                {t({
                  zh: `新建 ${result.created} · 绑定历史 ${result.merged} · 加入本班 ${result.joined ?? 0} · 已在班内 ${result.already_enrolled ?? 0} · 跳过 ${result.skipped}`,
                  en: `${result.created} created · ${result.merged} linked · ${result.joined ?? 0} joined this class · ${result.already_enrolled ?? 0} already in class · ${result.skipped} skipped`,
                })}
              </p>
              {result.rows.some(
                (r) =>
                  r.status === "joined_existing" ||
                  r.status === "already_enrolled",
              ) && (
                <ul className="mt-2 list-inside list-disc text-muted-foreground">
                  {result.rows
                    .filter(
                      (r) =>
                        r.status === "joined_existing" ||
                        r.status === "already_enrolled",
                    )
                    .map((r) => (
                      <li key={r.username}>
                        {r.status === "joined_existing"
                          ? t({
                              zh: `${r.username}（${r.full_name}）：使用原有账号加入本班，密码不变`,
                              en: `${r.username} (${r.full_name}): joined this class with the existing account; password unchanged`,
                            })
                          : t({
                              zh: `${r.username}（${r.full_name}）：已在本班，未改动`,
                              en: `${r.username} (${r.full_name}): already in this class, unchanged`,
                            })}
                      </li>
                    ))}
                </ul>
              )}
              {result.rows.some((r) => r.error) && (
                <ul className="mt-2 list-inside list-disc text-destructive">
                  {result.rows
                    .filter((r) => r.error)
                    .map((r) => (
                      <li key={r.username}>
                        {t({
                          zh: `${r.username}：${localizedDetail(r.error ?? "")}`,
                          en: `${r.username}: ${localizedDetail(r.error ?? "")}`,
                        })}
                      </li>
                    ))}
                </ul>
              )}
            </div>
          )}
        </div>
        <DialogFooter className="flex-row gap-2">
          <LoadingButton
            disabled={lines.length === 0}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {t({ zh: "导入", en: "Import" })}
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
  const { t } = useI18n()
  const rosterQuery = useQuery({
    queryKey: ["students", classroomId],
    queryFn: () => StudentsService.listStudents({ classroomId }),
    enabled: open,
  })
  const [removeTarget, setRemoveTarget] = useState<string | null>(null)
  const [bulkConfirm, setBulkConfirm] = useState(false)
  const [bulkDone, setBulkDone] = useState<number | null>(null)

  const resetMutation = useMutation({
    mutationFn: (studentId: string) =>
      StudentsService.resetStudentPassword({ studentId }),
    onSuccess: () => {
      showSuccessToast(
        t({
          zh: "已重置为默认密码 brs123456",
          en: "Password reset to the default brs123456",
        }),
      )
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `重置失败：${error.message}`,
          en: `Reset failed: ${error.message}`,
        }),
      ),
  })

  const resetPendingId = resetMutation.isPending
    ? (resetMutation.variables as string | undefined)
    : null

  const bulkResetMutation = useMutation({
    mutationFn: () => StudentsService.bulkResetPasswords({ classroomId }),
    onSuccess: (res) => {
      setBulkDone(res.reset)
      showSuccessToast(
        t({
          zh: `已重置 ${res.reset} 个账号为默认密码 brs123456`,
          en: `${res.reset} account(s) reset to the default password brs123456`,
        }),
      )
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `批量重置失败：${error.message}`,
          en: `Bulk reset failed: ${error.message}`,
        }),
      ),
  })

  const removeMutation = useMutation({
    mutationFn: (studentId: string) =>
      StudentsService.removeStudent({ studentId }),
    onSuccess: () => {
      showSuccessToast(
        t({
          zh: "已移出课堂（档案与历史保留）",
          en: "Removed from the classroom (profile and history kept)",
        }),
      )
      setRemoveTarget(null)
      void rosterQuery.refetch()
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `移出失败：${error.message}`,
          en: `Failed to remove: ${error.message}`,
        }),
      ),
  })

  const students = rosterQuery.data ?? []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {t({ zh: "学生名单", en: "Student Roster" })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "学号账号与状态；忘记密码时重置为默认密码 brs123456。",
              en: "Student ID accounts and status; reset to the default password brs123456 when forgotten.",
            })}
          </DialogDescription>
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "学生可自行修改密码；重置后已修改的密码会被覆盖回默认。",
                en: "Students can change their own passwords; a reset overwrites changed passwords with the default.",
              })}
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setBulkConfirm(true)}
            >
              {t({
                zh: "全部重置为默认密码",
                en: "Reset All to Default Password",
              })}
            </Button>
          </div>
          {bulkDone !== null && (
            <div className="rounded-md border bg-muted/40 p-3 text-sm">
              {t({
                zh: `已重置 ${bulkDone} 个账号为默认密码 brs123456。`,
                en: `${bulkDone} account(s) reset to the default password brs123456.`,
              })}
            </div>
          )}
        </DialogHeader>
        {rosterQuery.isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : students.length === 0 ? (
          <p className="py-6 text-center text-muted-foreground">
            {t({
              zh: "还没有学生账号，先「导入学生」。",
              en: 'No student accounts yet — start with "Import Students".',
            })}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t({ zh: "姓名", en: "Name" })}</TableHead>
                <TableHead>{t({ zh: "学号", en: "Student ID" })}</TableHead>
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
                  <TableCell className="text-right">
                    {s.username && (
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={t({
                            zh: "重置密码",
                            en: "Reset Password",
                          })}
                          disabled={resetPendingId === s.student.id}
                          onClick={() => {
                            resetMutation.mutate(s.student.id)
                          }}
                        >
                          <RotateCcw className="size-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={t({
                            zh: "移出课堂",
                            en: "Remove from classroom",
                          })}
                          onClick={() => setRemoveTarget(s.student.id)}
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
        open={removeTarget !== null}
        title={t({
          zh: "把该学生移出课堂？",
          en: "Remove this student from the classroom?",
        })}
        description={t({
          zh: "仅解除账号与课堂的绑定；练习档案与作答历史保留，重新导入相同学号可找回。",
          en: "Only unlinks the account from the classroom; practice profiles and answer history are kept, and re-importing the same student ID restores access.",
        })}
        confirmText={t({
          zh: "移出课堂",
          en: "Remove from Classroom",
        })}
        onOpenChange={(next) => {
          if (!next) setRemoveTarget(null)
        }}
        onConfirm={async () => {
          if (removeTarget) await removeMutation.mutateAsync(removeTarget)
        }}
      />

      <Dialog
        open={bulkConfirm}
        onOpenChange={(v) => {
          setBulkConfirm(v)
          if (!v) setBulkDone(null)
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>
              {t({
                zh: "全部重置为默认密码？",
                en: "Reset all to the default password?",
              })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "课堂内全部已绑定账号的密码将统一重置为默认密码 brs123456（学生自行修改过的密码也会被覆盖）。确定继续？",
                en: "All linked accounts in this classroom will be reset to the default password brs123456 (including passwords students changed themselves). Continue?",
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkConfirm(false)}>
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <LoadingButton
              loading={bulkResetMutation.isPending}
              onClick={() => {
                bulkResetMutation.mutate()
                setBulkConfirm(false)
              }}
            >
              {t({ zh: "重置全部", en: "Reset All" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Dialog>
  )
}
