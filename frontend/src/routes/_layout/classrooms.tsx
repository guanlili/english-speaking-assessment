import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ChevronDown, ClipboardPaste, Copy, Plus } from "lucide-react"
import { useState } from "react"
import { ClassesService } from "@/client"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import StudentImportDialog from "@/components/Teaching/StudentImportDialog"
import StudentRosterDialog from "@/components/Teaching/StudentRosterDialog"
import { TeachingPageHeader } from "@/components/Teaching/TeachingPageHeader"
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
import { NumberInput } from "@/components/ui/number-input"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"
import { copyText } from "@/lib/clipboard"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"

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
  const [classSize, setClassSize] = useState(60)
  const createMutation = useMutation({
    mutationFn: () =>
      ClassesService.createClass({
        classroomCreate: {
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
      <TeachingPageHeader
        eyebrow={t({ zh: "教学工作台", en: "Teaching workspace" })}
        title={t({ zh: "我的课堂", en: "My Classrooms" })}
        description={t({
          zh: "从课堂开始，安排练习、听评作答，关注每位学生的进步。",
          en: "Open a classroom to assign practice, review recordings and follow each student's progress.",
        })}
        actions={
          <Button variant="secondary" onClick={() => setCreateOpen(true)}>
            <Plus />
            {t({ zh: "新建课堂", en: "New Classroom" })}
          </Button>
        }
      />
      <details className="group rounded-xl border bg-card px-5">
        <summary className="flex min-h-11 cursor-pointer items-center justify-between gap-2 text-sm font-medium text-primary">
          {t({
            zh: "教学流程指南 · 课前 / 课中 / 课后",
            en: "Teaching guide · Before / during / after class",
          })}
          <ChevronDown className="size-4 shrink-0 transition-transform group-open:rotate-180" />
        </summary>
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
            <div key={step.title.zh} className="flex gap-3 py-4 pr-4">
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
      </details>
      <Card className="gap-0 overflow-hidden border-primary/10 py-0 shadow-sm">
        <CardHeader className="border-b bg-muted/30 py-5">
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
        <CardContent className="space-y-5 py-5">
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
            className="min-h-11 w-full sm:max-w-sm"
          />

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
    show_report_percentile?: boolean
  }
  onInvalidated: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { t } = useI18n()
  const [importOpen, setImportOpen] = useState(false)
  const [rosterOpen, setRosterOpen] = useState(false)
  const [sizeOpen, setSizeOpen] = useState(false)
  const [sizeValue, setSizeValue] = useState(classroom.class_size)

  const percentileOn = classroom.show_report_percentile !== false
  const percentileMutation = useMutation({
    mutationFn: (next: boolean) =>
      ClassesService.updateReportSettings({
        code: classroom.code,
        reportSettingsUpdate: { show_report_percentile: next },
      }),
    onSuccess: (_data, next) => {
      showSuccessToast(
        next
          ? t({
              zh: "学情报告会显示班级位置",
              en: "Learning reports will include class position",
            })
          : t({
              zh: "学情报告不再显示班级位置",
              en: "Learning reports will hide class position",
            }),
      )
      onInvalidated()
    },
    onError: (error) => showErrorToast(extractErrorMessage(error)),
  })

  const sizeMutation = useMutation({
    mutationFn: (next: number) =>
      ClassesService.updateClassSize({
        code: classroom.code,
        classSizeUpdate: { class_size: next },
      }),
    onSuccess: (data) => {
      showSuccessToast(
        t({
          zh: `人数上限已调整为 ${data.class_size} 人`,
          en: `Class size limit updated to ${data.class_size}`,
        }),
      )
      setSizeOpen(false)
      onInvalidated()
    },
    onError: (error) => showErrorToast(extractErrorMessage(error)),
  })

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
      ClassesService.deleteClass({
        code: classroom.code,
        delete_history: true,
      }),
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
    <Card className="h-full gap-0 border-primary/15 shadow-none transition-shadow hover:shadow-md">
      <CardHeader className="flex flex-wrap items-start justify-between gap-3 space-y-0 pb-4">
        <div className="min-w-0 flex-1">
          <CardTitle className="break-words text-lg">
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
      <CardContent className="flex flex-1 flex-col gap-4">
        <p className="flex-1 break-words text-sm leading-6 text-muted-foreground">
          {classroom.teaching_goal ||
            t({
              zh: "安排本次练习，查看学生作答与录音。",
              en: "Assign practice and review student answers and recordings.",
            })}
        </p>
        <div className="grid gap-2 xl:grid-cols-2 [&_a]:min-h-11 [&_button]:min-h-11">
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
        <details className="group border-t pt-3">
          <summary className="flex min-h-11 cursor-pointer items-center justify-between gap-2 text-sm font-medium text-muted-foreground">
            {t({
              zh: "学生管理 · 名单与账号",
              en: "Students · Roster & Accounts",
            })}
            <ChevronDown className="size-4 shrink-0 transition-transform group-open:rotate-180" />
          </summary>
          <div className="mt-3 flex flex-wrap gap-2 [&_button]:min-h-11">
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
              variant="outline"
              size="sm"
              onClick={() => {
                setSizeValue(classroom.class_size)
                setSizeOpen(true)
              }}
            >
              {t({
                zh: `人数上限 ${classroom.class_size}`,
                en: `Size Limit ${classroom.class_size}`,
              })}
            </Button>
            <label
              htmlFor={`report-percentile-${classroom.code}`}
              className="flex min-h-11 w-full items-center gap-3 text-sm"
            >
              <Checkbox
                id={`report-percentile-${classroom.code}`}
                checked={percentileOn}
                disabled={percentileMutation.isPending}
                onCheckedChange={(checked) =>
                  percentileMutation.mutate(checked === true)
                }
              />
              <span>
                {t({
                  zh: "学情报告显示班级位置",
                  en: "Show class position on learning reports",
                })}
              </span>
            </label>
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
      <Dialog open={sizeOpen} onOpenChange={setSizeOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {t({
                zh: `调整 ${classroom.code} 的人数上限`,
                en: `Adjust Size Limit for ${classroom.code}`,
              })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "上限只限制新学生加入（导入/自加入），已入班学生不受影响；不能低于班内现有档案数。",
                en: "The limit only gates new students joining (import or self-join); enrolled students are unaffected. It cannot go below the current roster size.",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="class-size-edit">
              {t({
                zh: "班级人数上限（1-100）",
                en: "Class size limit (1-100)",
              })}
            </Label>
            <NumberInput
              id="class-size-edit"
              min={1}
              max={100}
              value={sizeValue}
              onValueChange={setSizeValue}
            />
          </div>
          <DialogFooter>
            <LoadingButton
              disabled={
                !Number.isInteger(sizeValue) || sizeValue < 1 || sizeValue > 100
              }
              loading={sizeMutation.isPending}
              onClick={() => sizeMutation.mutate(sizeValue)}
            >
              {t({ zh: "保存", en: "Save" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
