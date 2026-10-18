import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useId, useRef, useState } from "react"
import { ApiError, type BoardStudent, ClassesService } from "@/client"
import { HelpReplyEditor } from "@/components/Teaching/HelpReplyEditor"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { helpCategories } from "@/lib/classroom-message-labels"
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"
import { randomId } from "@/utils"

export function ClassroomContactPanel({
  code,
  students,
}: {
  code: string
  students: BoardStudent[]
}) {
  const { t, lang } = useI18n()
  const deadlineId = useId()
  const client = useQueryClient()
  const identity = useRef(localStorage.getItem("access_token"))
  const [helpStatus, setHelpStatus] = useState<"open" | "all">("open")
  const [reminderStatus, setReminderStatus] = useState<"open" | "all">("all")
  const [deadline, setDeadline] = useState("")
  const repeatRequests = useRef<Record<string, string>>({})
  const [studentIds, setStudentIds] = useState<string[]>([])
  const [text, setText] = useState(
    "请继续完成本次课堂练习；如已提交，请等待评分。\nPlease complete the classroom practice. If already submitted, wait for scoring.",
  )
  const [helpOffset, setHelpOffset] = useState(0)
  const [reminderOffset, setReminderOffset] = useState(0)
  const request = useRef({ signature: "", id: "" })
  const help = useQuery({
    queryKey: [
      "teacher",
      "class-messages",
      code,
      "help",
      helpStatus,
      helpOffset,
    ],
    queryFn: async () => {
      const rows = await ClassesService.readTeacherClassMessages({
        code,
        kind: "help",
        status: helpStatus,
        offset: helpOffset,
        limit: 4,
      })
      if (!Array.isArray(rows)) throw new Error("Invalid message response")
      return rows
    },
    refetchInterval: 5000,
  })
  const reminders = useQuery({
    queryKey: [
      "teacher",
      "class-messages",
      code,
      "reminder",
      reminderStatus,
      reminderOffset,
    ],
    queryFn: async () => {
      const rows = await ClassesService.readTeacherClassMessages({
        code,
        kind: "reminder",
        status: reminderStatus,
        offset: reminderOffset,
        limit: 11,
      })
      if (!Array.isArray(rows)) throw new Error("Invalid message response")
      return rows
    },
    refetchInterval: 10000,
  })
  const invalidate = () => {
    if (identity.current !== localStorage.getItem("access_token")) return
    void client.invalidateQueries({
      queryKey: ["teacher", "class-messages", code],
    })
  }
  const action = useMutation({
    mutationFn: ({
      id,
      action,
    }: {
      id: string
      action: "read" | "resolved"
    }) => {
      if (identity.current !== localStorage.getItem("access_token"))
        throw new Error("Session changed")
      return ClassesService.actOnClassMessage({ code, messageId: id, action })
    },
    onSuccess: () => {
      setHelpOffset(0)
      invalidate()
    },
  })
  const send = useMutation({
    mutationFn: () => {
      if (identity.current !== localStorage.getItem("access_token"))
        throw new Error("Session changed")
      const signature = JSON.stringify([
        text.trim(),
        [...studentIds].sort(),
        deadline,
      ])
      if (request.current.signature !== signature || !request.current.id)
        request.current = { signature, id: randomId() }
      return ClassesService.createClassReminders({
        code,
        requestBody: {
          request_id: request.current.id,
          student_ids: studentIds,
          text: text.trim(),
          due_at: deadline ? new Date(deadline).toISOString() : null,
        },
      })
    },
    onSuccess: () => {
      if (identity.current !== localStorage.getItem("access_token")) return
      invalidate()
      setStudentIds([])
      setReminderOffset(0)
      request.current = { signature: "", id: "" }
    },
  })
  const repeat = useMutation({
    mutationFn: (messageId: string) => {
      if (identity.current !== localStorage.getItem("access_token"))
        throw new Error("Session changed")
      repeatRequests.current[messageId] ??= randomId()
      return ClassesService.repeatClassReminder({
        code,
        messageId,
        requestBody: { request_id: repeatRequests.current[messageId] },
      })
    },
    onSuccess: (_, messageId) => {
      if (identity.current !== localStorage.getItem("access_token")) return
      delete repeatRequests.current[messageId]
      invalidate()
    },
  })
  return (
    <section
      aria-label={t({
        zh: "学生求助与站内提醒",
        en: "Student help and reminders",
      })}
      className="space-y-4 rounded-2xl border bg-card p-5"
    >
      <h2 className="font-semibold">
        {t({ zh: "学生求助与站内提醒", en: "Student help and reminders" })}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t({
          zh: "求助来自学生主动上报；老师查看后可标记已处理。站内提醒仅发给所选学生，已读表示学生主动确认，不代表练习已完成。",
          en: "Help is requested by students. Mark requests resolved after assisting. Reminders go only to selected students; read receipts mean explicit acknowledgment, not completed practice.",
        })}
      </p>
      <div className="space-y-3">
        <label className="flex flex-wrap items-center gap-3 text-sm">
          <span>{t({ zh: "求助记录", en: "Help requests" })}</span>
          <select
            className="min-h-11 rounded-md border bg-background px-3 text-base"
            aria-label={t({ zh: "求助记录", en: "Help requests" })}
            value={helpStatus}
            onChange={(event) => {
              setHelpStatus(event.target.value as typeof helpStatus)
              setHelpOffset(0)
            }}
          >
            <option value="open">{t({ zh: "待处理", en: "Open" })}</option>
            <option value="all">
              {t({ zh: "全部（含已处理）", en: "All (including resolved)" })}
            </option>
          </select>
        </label>
        <h3 className="font-medium">
          {t({ zh: "待处理求助", en: "Open help requests" })}
        </h3>
        {help.isPending ? (
          <p role="status">
            {t({ zh: "正在加载求助…", en: "Loading requests…" })}
          </p>
        ) : help.isError ? (
          <Button
            variant="outline"
            className="min-h-11"
            onClick={() => void help.refetch()}
          >
            {t({ zh: "求助加载失败，重试", en: "Requests unavailable. Retry" })}
          </Button>
        ) : !help.data?.length ? (
          <p className="text-sm text-muted-foreground">
            {t({ zh: "暂无待处理求助。", en: "No open help requests." })}
          </p>
        ) : (
          help.data.slice(0, 3).map((row) => (
            <article className="space-y-2 rounded-xl border p-3" key={row.id}>
              <p className="break-words font-medium">
                {row.display_name} ·{" "}
                {row.category && row.category in helpCategories
                  ? t(
                      helpCategories[
                        row.category as keyof typeof helpCategories
                      ],
                    )
                  : t(helpCategories.other)}
              </p>
              {row.text && (
                <p className="whitespace-pre-wrap break-words text-sm">
                  {row.text}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                {formatDateTime(row.created_at, lang)} ·{" "}
                {row.read_at
                  ? t({ zh: "已查看", en: "Seen" })
                  : t({ zh: "尚未查看", en: "Not yet seen" })}
              </p>
              {row.reply_text && (
                <p className="whitespace-pre-wrap break-words text-sm">
                  {t({ zh: "教师答复：", en: "Teacher reply: " })}
                  {row.reply_text}
                </p>
              )}
              {row.resolved_at && (
                <p className="text-sm">
                  {row.resolution === "withdrawn"
                    ? t({ zh: "学生已撤回", en: "Withdrawn by student" })
                    : t({ zh: "已处理", en: "Resolved" })}
                </p>
              )}
              {!row.resolved_at && (
                <div className="flex flex-wrap gap-2">
                  {!row.read_at && (
                    <Button
                      variant="outline"
                      className="min-h-11"
                      disabled={action.isPending}
                      onClick={() =>
                        action.mutate({ id: row.id, action: "read" })
                      }
                    >
                      {t({ zh: "标记已查看", en: "Mark seen" })}
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    className="min-h-11"
                    disabled={action.isPending}
                    onClick={() =>
                      action.mutate({ id: row.id, action: "resolved" })
                    }
                  >
                    {t({
                      zh: "已帮助，标记处理完成",
                      en: "Helped — mark resolved",
                    })}
                  </Button>
                </div>
              )}
              {row.resolution !== "withdrawn" && (
                <HelpReplyEditor key={row.id} code={code} message={row} />
              )}
            </article>
          ))
        )}
        <div className="flex flex-wrap gap-2">
          {helpOffset > 0 && (
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() => setHelpOffset((value) => Math.max(0, value - 3))}
            >
              {t({ zh: "上一页求助", en: "Previous requests" })}
            </Button>
          )}
          {(help.data?.length ?? 0) > 3 && (
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() => setHelpOffset((value) => value + 3)}
            >
              {t({ zh: "更多求助", en: "More requests" })}
            </Button>
          )}
        </div>
      </div>
      <details>
        <summary className="min-h-11 cursor-pointer py-3 font-medium">
          {t({ zh: "向学生发送站内提醒", en: "Send students a reminder" })}
        </summary>
        <fieldset disabled={send.isPending} className="min-w-0 space-y-3 pt-3">
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() =>
                setStudentIds(
                  students
                    .filter((row) =>
                      row.items.some(
                        (item) =>
                          item.type !== "instruction" &&
                          item.status === "missing",
                      ),
                    )
                    .map((row) => row.student_id),
                )
              }
            >
              {t({
                zh: "选择仍有未提交题目的学生",
                en: "Select students with missing answers",
              })}
            </Button>
            <Button
              variant="ghost"
              className="min-h-11"
              onClick={() => setStudentIds([])}
            >
              {t({ zh: "清空提醒名单", en: "Clear recipients" })}
            </Button>
          </div>
          <div className="grid max-h-60 gap-2 overflow-y-auto sm:grid-cols-2">
            {students.map((row) => (
              <label
                key={row.student_id}
                className="flex min-h-11 items-center gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  className="size-5"
                  checked={studentIds.includes(row.student_id)}
                  onChange={() =>
                    setStudentIds(
                      studentIds.includes(row.student_id)
                        ? studentIds.filter((id) => id !== row.student_id)
                        : [...studentIds, row.student_id],
                    )
                  }
                />
                <span className="min-w-0 break-words">
                  {row.display_name}
                  {row.suffix && `·${row.suffix}`}
                </span>
              </label>
            ))}
          </div>
          <label htmlFor={deadlineId} className="block space-y-2 text-sm">
            <span>
              {t({
                zh: "提醒截止时间（可选，不会改变考试时间）",
                en: "Reminder deadline (optional; does not change exam time)",
              })}
            </span>
            <Input
              id={deadlineId}
              type="datetime-local"
              className="text-base"
              value={deadline}
              onChange={(event) => setDeadline(event.target.value)}
              aria-label={t({ zh: "提醒截止时间", en: "Reminder deadline" })}
            />
          </label>
          <Textarea
            aria-label={t({ zh: "站内提醒内容", en: "Reminder text" })}
            className="min-h-28 text-base"
            maxLength={500}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <Button
            className="min-h-11"
            disabled={!studentIds.length || !text.trim()}
            onClick={() => send.mutate()}
          >
            {t({
              zh: `发送提醒给 ${studentIds.length} 人`,
              en: `Send reminder to ${studentIds.length} students`,
            })}
          </Button>
        </fieldset>
      </details>
      {send.isSuccess && (
        <p role="status">
          {t({
            zh: "提醒已发送，可在下面查看学生是否已读。",
            en: "Reminder sent. Check read receipts below.",
          })}
        </p>
      )}
      {repeat.isError && (
        <p role="alert" className="text-sm text-destructive">
          {repeat.error instanceof ApiError && repeat.error.status === 429
            ? t({
                zh: "请至少间隔一分钟再次提醒。",
                en: "Wait at least one minute before reminding again.",
              })
            : repeat.error instanceof ApiError && repeat.error.status === 409
              ? t({
                  zh: "该提醒已被学生确认，请刷新回执。",
                  en: "The student already acknowledged this reminder. Refresh receipts.",
                })
              : t({
                  zh: "再次提醒失败，请重试。",
                  en: "Could not remind again. Retry.",
                })}
        </p>
      )}
      {(send.isError || action.isError) && (
        <p role="alert" className="text-sm text-destructive">
          {send.error instanceof ApiError &&
          (send.error.body as { detail?: string })?.detail ===
            "Reminder deadline must be in future"
            ? t({
                zh: "提醒截止时间必须晚于当前时间，请修改后重试。",
                en: "The reminder deadline must be in the future. Update it and retry.",
              })
            : t({
                zh: "操作失败，当前输入和选择已保留，请重试。",
                en: "Action failed. Your input and selection are kept; retry.",
              })}
        </p>
      )}
      <details>
        <summary className="min-h-11 cursor-pointer py-3 font-medium">
          {t({
            zh: "最近提醒与已读回执",
            en: "Recent reminders and read receipts",
          })}
        </summary>
        <label className="mb-3 flex flex-wrap items-center gap-3 text-sm">
          <span>{t({ zh: "提醒状态", en: "Reminder status" })}</span>
          <select
            className="min-h-11 rounded-md border bg-background px-3 text-base"
            aria-label={t({ zh: "提醒状态", en: "Reminder status" })}
            value={reminderStatus}
            onChange={(event) => {
              setReminderStatus(event.target.value as typeof reminderStatus)
              setReminderOffset(0)
            }}
          >
            <option value="all">
              {t({ zh: "全部提醒", en: "All reminders" })}
            </option>
            <option value="open">
              {t({ zh: "仅未读", en: "Unread only" })}
            </option>
          </select>
        </label>
        {reminders.isError ? (
          <Button
            variant="outline"
            className="min-h-11"
            onClick={() => void reminders.refetch()}
          >
            {t({ zh: "回执加载失败，重试", en: "Receipts unavailable. Retry" })}
          </Button>
        ) : !reminders.data?.length ? (
          <p className="text-sm">
            {t({ zh: "暂无提醒。", en: "No reminders yet." })}
          </p>
        ) : (
          reminders.data.slice(0, 10).map((row) => (
            <article className="space-y-1 rounded-xl border p-3" key={row.id}>
              <p className="break-words text-sm font-medium">
                {row.display_name} ·{" "}
                {row.read_at
                  ? t({ zh: "已读", en: "Read" })
                  : t({ zh: "未读", en: "Unread" })}
              </p>
              <p className="whitespace-pre-wrap break-words text-sm">
                {row.text}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatDateTime(row.read_at ?? row.created_at, lang)}
              </p>
              {row.due_at && (
                <p className="text-sm">
                  {t({ zh: "截止：", en: "Due: " })}
                  {formatDateTime(row.due_at, lang)}
                  {!row.read_at &&
                    new Date(row.due_at).getTime() < Date.now() &&
                    ` · ${t({ zh: "已过期，尚未确认", en: "Past due, not acknowledged" })}`}
                </p>
              )}
              {!row.read_at && (
                <Button
                  variant="outline"
                  className="min-h-11"
                  disabled={repeat.isPending}
                  onClick={() => repeat.mutate(row.id)}
                >
                  {t({ zh: "再次提醒", en: "Remind again" })}
                </Button>
              )}
            </article>
          ))
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {reminderOffset > 0 && (
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() =>
                setReminderOffset((value) => Math.max(0, value - 10))
              }
            >
              {t({ zh: "上一页回执", en: "Previous receipts" })}
            </Button>
          )}
          {(reminders.data?.length ?? 0) > 10 && (
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() => setReminderOffset((value) => value + 10)}
            >
              {t({ zh: "更多回执", en: "More receipts" })}
            </Button>
          )}
        </div>
      </details>
    </section>
  )
}
