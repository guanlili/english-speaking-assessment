import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { ApiError, type BoardStudent, ClassesService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"

export function FollowupManager({
  code,
  students,
  currentExerciseId,
}: {
  code: string
  students: BoardStudent[]
  currentExerciseId?: string | null
}) {
  const { t, lang } = useI18n()
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const tasks = useQuery({
    queryKey: ["teacher", "followups", code],
    queryFn: () => ClassesService.listClassFollowups({ code }),
    refetchInterval: 10000,
  })
  const cancel = useMutation({
    mutationFn: (taskId: string) =>
      ClassesService.cancelClassFollowup({ code, taskId }),
    onSuccess: () => {
      void client.invalidateQueries({
        queryKey: ["teacher", "followups", code],
      })
    },
    onError: () =>
      toast.error(
        t({
          zh: "撤销失败，请重试。",
          en: "Could not withdraw. Please retry.",
        }),
      ),
  })
  return (
    <section
      className="space-y-4 rounded-2xl border bg-card p-5"
      aria-label={t({ zh: "指定学生补练", en: "Targeted practice" })}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">
            {t({ zh: "指定学生补练", en: "Targeted practice" })}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t({
              zh: "独立发布给选中学生，不替换全班当前练习。显示最近 50 项任务。",
              en: "Assign separately to selected students without replacing class practice. Showing the latest 50 tasks.",
            })}
          </p>
        </div>
        <Button className="min-h-11" onClick={() => setOpen(true)}>
          {t({ zh: "布置补练", en: "Assign targeted practice" })}
        </Button>
      </div>
      {open && (
        <FollowupCreateDialog
          code={code}
          students={students}
          initialSource={currentExerciseId ?? ""}
          onClose={() => setOpen(false)}
        />
      )}
      {tasks.isError ? (
        <Button
          variant="outline"
          className="min-h-11"
          onClick={() => void tasks.refetch()}
        >
          {t({
            zh: "补练加载失败，点击重试",
            en: "Could not load tasks. Retry",
          })}
        </Button>
      ) : tasks.isPending ? (
        <p role="status">{t({ zh: "正在加载…", en: "Loading…" })}</p>
      ) : (tasks.data ?? []).length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t({
            zh: "尚未布置补练。",
            en: "No targeted practice assigned yet.",
          })}
        </p>
      ) : (
        (tasks.data ?? []).map((task) => (
          <article key={task.id} className="space-y-3 rounded-xl border p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0 break-words">
                <h3 className="font-medium">{task.title}</h3>
                <p className="text-xs text-muted-foreground">
                  {task.created_at && formatDateTime(task.created_at, lang)} ·{" "}
                  {t({
                    zh: `${task.item_count} 题 · ${task.targets.filter((row) => row.done_count === row.total_count).length}/${task.targets.length} 人完成`,
                    en: `${task.item_count} items · ${task.targets.filter((row) => row.done_count === row.total_count).length}/${task.targets.length} completed`,
                  })}
                </p>
              </div>
              {task.status === "followup_closed" ? (
                <span className="text-sm">
                  {t({ zh: "已撤销", en: "Withdrawn" })}
                </span>
              ) : (
                <Button
                  variant="outline"
                  className="min-h-11"
                  disabled={cancel.isPending}
                  onClick={() => {
                    if (
                      window.confirm(
                        t({
                          zh: "撤销后学生不能继续提交，已有记录保留。确认撤销？",
                          en: "Withdraw this task? Further submissions will be blocked; existing records are kept.",
                        }),
                      )
                    )
                      cancel.mutate(task.id)
                  }}
                >
                  {t({ zh: "撤销补练", en: "Withdraw task" })}
                </Button>
              )}
            </div>
            <ul className="grid gap-2 text-sm sm:grid-cols-2">
              {task.targets.map((row) => (
                <li key={row.student_id} className="min-w-0 break-words">
                  {row.display_name} · {row.done_count}/{row.total_count}{" "}
                  {row.has_pending
                    ? t({ zh: "评分中", en: "Scoring" })
                    : row.has_failures
                      ? t({
                          zh: "有评分失败",
                          en: "Scoring failed",
                        })
                      : null}
                </li>
              ))}
            </ul>
          </article>
        ))
      )}
    </section>
  )
}

function FollowupCreateDialog({
  code,
  students,
  initialSource,
  onClose,
}: {
  code: string
  students: BoardStudent[]
  initialSource: string
  onClose: () => void
}) {
  const { t } = useI18n()
  const client = useQueryClient()
  const identity = useRef(localStorage.getItem("access_token"))
  const [title, setTitle] = useState(
    t({ zh: "课后巩固练习", en: "Follow-up speaking practice" }),
  )
  const [source, setSource] = useState(initialSource)
  const [studentIds, setStudentIds] = useState<string[]>([])
  const [itemIds, setItemIds] = useState<string[]>([])
  const [rule, setRule] = useState<
    "low_score" | "short_answer" | "missed_word" | "teacher_focus"
  >("low_score")
  const [word, setWord] = useState("")
  const [diagnosticMessage, setDiagnosticMessage] = useState("")
  const initialized = useRef("")
  const suggest = useMutation({
    mutationFn: () =>
      ClassesService.readDiagnosticTargets({ code, rule, word }),
    onSuccess: (result) => {
      if (localStorage.getItem("access_token") !== identity.current) return
      setSource(result.source_exercise_id)
      initialized.current = result.source_exercise_id
      setStudentIds(result.student_ids)
      setItemIds(result.item_ids)
      setDiagnosticMessage(
        t({
          zh: `匹配 ${result.student_ids.length} 人、${result.item_ids.length} 题。请核对下方题目和接收名单后发布。`,
          en: `Matched ${result.student_ids.length} students and ${result.item_ids.length} items. Review items and recipients below before assigning.`,
        }),
      )
    },
  })
  const exercises = useQuery({
    queryKey: ["teacher", "exercises", code],
    queryFn: () => ClassesService.listClassroomExercises({ code }),
  })
  const sourceId = source || exercises.data?.[0]?.id || ""
  const items = useQuery({
    queryKey: ["teacher", "followup-items", code, sourceId],
    queryFn: () =>
      ClassesService.readFollowupItems({ code, exerciseId: sourceId }),
    enabled: Boolean(sourceId),
    refetchOnWindowFocus: false,
  })
  useEffect(() => {
    if (items.data && initialized.current !== sourceId) {
      initialized.current = sourceId
      setItemIds(items.data.map((item) => item.id))
    }
  }, [sourceId, items.data])
  const toggle = (values: string[], id: string) =>
    values.includes(id)
      ? values.filter((value) => value !== id)
      : [...values, id]
  const create = useMutation({
    mutationFn: () => {
      if (localStorage.getItem("access_token") !== identity.current)
        throw new Error("Session changed")
      return ClassesService.createClassFollowup({
        code,
        requestBody: {
          source_exercise_id: sourceId,
          title: title.trim(),
          student_ids: studentIds,
          item_ids: itemIds,
        },
      })
    },
    onSuccess: () => {
      if (localStorage.getItem("access_token") !== identity.current) return
      void client.invalidateQueries({
        queryKey: ["teacher", "followups", code],
      })
      toast.success(
        t({
          zh: "补练已发布给选中学生。",
          en: "Targeted practice assigned to selected students.",
        }),
      )
      onClose()
    },
  })
  const detail =
    create.error instanceof ApiError
      ? (create.error.body as { detail?: string })?.detail
      : undefined
  const examBlocked =
    detail === "Active exam cannot be assigned as followup" ||
    detail === "Student exam still in progress"
  return (
    <Dialog
      open
      onOpenChange={(value) => {
        if (!value && !create.isPending) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t({ zh: "布置指定补练", en: "Assign targeted practice" })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "使用原发布时的题目快照，只发给所选学生；不修改原成绩或全班题单。当前考试不能复制，历史考试中仍在作答的学生需先结束考试。",
              en: "Uses the original published item snapshot for selected students only. Original results and class practice stay unchanged. Current exams cannot be copied; students must finish an earlier exam before receiving its follow-up.",
            })}
          </DialogDescription>
        </DialogHeader>
        <fieldset
          disabled={create.isPending || suggest.isPending}
          className="min-w-0 space-y-4"
        >
          <div className="space-y-3 rounded-xl border p-3">
            <h3 className="font-medium">
              {t({
                zh: "按今日诊断选择补练",
                en: "Choose practice from today's diagnostics",
              })}
            </h3>
            <p className="text-sm text-muted-foreground">
              {t({
                zh: "使用当前发布的每人每题最近一次作答。问答少于 15 词仅作教学提示；请核对转写。当前考试不可用于筛选。",
                en: "Uses each student's latest answer per item in the current publication. Q&A under 15 words is a teaching hint; check the transcript. Current exams cannot be selected.",
              })}
            </p>
            <label className="block space-y-2">
              <span>{t({ zh: "筛选条件", en: "Filter" })}</span>
              <select
                className="min-h-11 w-full rounded-md border bg-background px-3 text-base"
                value={rule}
                onChange={(event) => setRule(event.target.value as typeof rule)}
                disabled={suggest.isPending}
              >
                <option value="low_score">
                  {t({ zh: "参考分低于 70", en: "Reference score below 70" })}
                </option>
                <option value="short_answer">
                  {t({ zh: "问答少于 15 词", en: "Q&A under 15 words" })}
                </option>
                <option value="missed_word">
                  {t({
                    zh: "转写中漏掉指定内容词",
                    en: "Specific content word missing in transcript",
                  })}
                </option>
                <option value="teacher_focus">
                  {t({ zh: "教师重点关注", en: "Teacher focus area" })}
                </option>
              </select>
            </label>
            {rule === "missed_word" && (
              <Input
                aria-label={t({
                  zh: "要查找的英文内容词",
                  en: "English content word to find",
                })}
                maxLength={100}
                value={word}
                onChange={(event) => setWord(event.target.value)}
              />
            )}
            <Button
              variant="outline"
              className="min-h-11"
              disabled={
                suggest.isPending || (rule === "missed_word" && !word.trim())
              }
              onClick={() => {
                setDiagnosticMessage("")
                suggest.mutate()
              }}
            >
              {t({
                zh: "筛选学生和原题",
                en: "Find students and source items",
              })}
            </Button>
            {suggest.isError && (
              <p role="alert">
                {t({
                  zh: "筛选失败，可能尚无当前练习或正在考试；原有选择已保留。",
                  en: "Could not filter; there may be no current practice or an exam is active. Existing selections are kept.",
                })}
              </p>
            )}
            {diagnosticMessage && (
              <p role="status" className="text-sm">
                {diagnosticMessage}
              </p>
            )}
          </div>
          <label
            htmlFor="followup-task-title"
            className="block space-y-2 text-sm"
          >
            <span>{t({ zh: "补练名称", en: "Task title" })}</span>
            <Input
              id="followup-task-title"
              maxLength={255}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label className="block space-y-2 text-sm">
            <span>{t({ zh: "来源练习", en: "Source practice" })}</span>
            <select
              className="min-h-11 w-full rounded-md border px-3 text-base"
              value={sourceId}
              onChange={(event) => {
                setSource(event.target.value)
                setItemIds([])
                initialized.current = ""
              }}
            >
              {(exercises.data ?? []).map((exercise) => (
                <option key={exercise.id} value={exercise.id}>
                  {exercise.title} · v{exercise.version_no}
                </option>
              ))}
            </select>
          </label>
          {(items.isError || exercises.isError) && (
            <p role="alert">
              {t({
                zh: "来源题单加载失败，请关闭后重试。",
                en: "Could not load source items. Close and retry.",
              })}
            </p>
          )}
          <fieldset className="min-w-0 space-y-1">
            <legend className="font-medium">
              {t({ zh: "选择补练题目", en: "Select practice items" })}
            </legend>
            <div className="max-h-60 overflow-y-auto">
              {(items.data ?? []).map((item, index) => (
                <label
                  key={item.id}
                  className="flex min-h-11 items-center gap-3 py-2 text-sm"
                >
                  <input
                    type="checkbox"
                    className="size-5 shrink-0"
                    checked={itemIds.includes(item.id)}
                    onChange={() => setItemIds(toggle(itemIds, item.id))}
                  />
                  <span className="min-w-0 break-words">
                    {index + 1}. {item.text}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="min-w-0 space-y-1">
            <legend className="font-medium">
              {t({ zh: "选择接收学生", en: "Select recipients" })}
            </legend>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                className="min-h-11"
                onClick={() =>
                  setStudentIds(students.map((student) => student.student_id))
                }
              >
                {t({ zh: "全选学生", en: "Select all students" })}
              </Button>
              <Button
                variant="ghost"
                className="min-h-11"
                onClick={() => setStudentIds([])}
              >
                {t({ zh: "清空选择", en: "Clear selection" })}
              </Button>
            </div>
            <div className="grid max-h-60 gap-1 overflow-y-auto sm:grid-cols-2">
              {students.map((student) => (
                <label
                  key={student.student_id}
                  className="flex min-h-11 items-center gap-3 text-sm"
                >
                  <input
                    className="size-5"
                    type="checkbox"
                    checked={studentIds.includes(student.student_id)}
                    onChange={() =>
                      setStudentIds(toggle(studentIds, student.student_id))
                    }
                  />
                  <span className="min-w-0 break-words">
                    {student.display_name}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        </fieldset>
        {create.isError && (
          <p role="alert" className="text-sm text-destructive">
            {t(
              examBlocked
                ? {
                    zh: "当前考试或所选学生的考试尚未结束，暂不能发布这份补练。请使用普通练习或已结束的历史考试。",
                    en: "This exam is current or a recipient has not finished it. Use regular practice or a completed earlier exam.",
                  }
                : {
                    zh: "发布失败，选择已保留；请检查名单和题目后重试。",
                    en: "Assignment failed. Selections are kept; check recipients and items, then retry.",
                  },
            )}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            disabled={create.isPending}
          >
            {t({ zh: "取消", en: "Cancel" })}
          </Button>
          <Button
            className="min-h-11"
            disabled={
              create.isPending ||
              suggest.isPending ||
              !title.trim() ||
              !sourceId ||
              !studentIds.length ||
              !itemIds.length ||
              items.isFetching ||
              items.isError
            }
            onClick={() => create.mutate()}
          >
            {t({
              zh: `确认布置给 ${studentIds.length} 人`,
              en: `Assign to ${studentIds.length} ${studentIds.length === 1 ? "student" : "students"}`,
            })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
