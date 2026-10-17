import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { type BoardStudent, ClassesService } from "@/client"
import { Button } from "@/components/ui/button"
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
  const client = useQueryClient()
  const identity = useRef(localStorage.getItem("access_token"))
  const [studentIds, setStudentIds] = useState<string[]>([])
  const [text, setText] = useState(
    "请继续完成本次课堂练习；如已提交，请等待评分。\nPlease complete the classroom practice. If already submitted, wait for scoring.",
  )
  const [helpOffset, setHelpOffset] = useState(0)
  const [reminderOffset, setReminderOffset] = useState(0)
  const request = useRef({ signature: "", id: "" })
  const help = useQuery({
    queryKey: ["teacher", "class-messages", code, "help", helpOffset],
    queryFn: async () => {
      const rows = await ClassesService.readTeacherClassMessages({
        code,
        kind: "help",
        status: "open",
        offset: helpOffset,
        limit: 21,
      })
      if (!Array.isArray(rows)) throw new Error("Invalid message response")
      return rows
    },
    refetchInterval: 5000,
  })
  const reminders = useQuery({
    queryKey: ["teacher", "class-messages", code, "reminder", reminderOffset],
    queryFn: async () => {
      const rows = await ClassesService.readTeacherClassMessages({
        code,
        kind: "reminder",
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
      const signature = JSON.stringify([text.trim(), [...studentIds].sort()])
      if (request.current.signature !== signature || !request.current.id)
        request.current = { signature, id: randomId() }
      return ClassesService.createClassReminders({
        code,
        requestBody: {
          request_id: request.current.id,
          student_ids: studentIds,
          text: text.trim(),
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
          help.data.slice(0, 20).map((row) => (
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
            </article>
          ))
        )}
        <div className="flex flex-wrap gap-2">
          {helpOffset > 0 && (
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() => setHelpOffset((value) => Math.max(0, value - 20))}
            >
              {t({ zh: "上一页求助", en: "Previous requests" })}
            </Button>
          )}
          {(help.data?.length ?? 0) > 20 && (
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() => setHelpOffset((value) => value + 20)}
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
      {(send.isError || action.isError) && (
        <p role="alert" className="text-sm text-destructive">
          {t({
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
