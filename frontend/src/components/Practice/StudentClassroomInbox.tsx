import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { ApiError, ClassesService, type HelpRequestWrite } from "@/client"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  classroomMessagesKey,
  useClassroomMessages,
} from "@/hooks/useClassroomMessages"
import { helpCategories } from "@/lib/classroom-message-labels"
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"
import { randomId } from "@/utils"

export function StudentClassroomInbox({ code }: { code: string }) {
  const { t, lang } = useI18n()
  const client = useQueryClient()
  const identity = useRef(localStorage.getItem("access_token"))
  const query = useClassroomMessages(code)
  const [category, setCategory] =
    useState<HelpRequestWrite["category"]>("operation")
  const [text, setText] = useState("")
  const [shown, setShown] = useState(20)
  const request = useRef({ signature: "", id: "" })
  const active = query.data?.find(
    (row) => row.kind === "help" && !row.resolved_at,
  )
  const lastResolvedHelp = query.data?.find(
    (row) => row.kind === "help" && row.resolved_at,
  )
  const invalidate = () => {
    if (identity.current !== localStorage.getItem("access_token")) return
    void client.invalidateQueries({ queryKey: classroomMessagesKey(code) })
  }
  const help = useMutation({
    mutationFn: () => {
      if (identity.current !== localStorage.getItem("access_token"))
        throw new Error("Session changed")
      const signature = JSON.stringify([category, text.trim()])
      if (request.current.signature !== signature || !request.current.id)
        request.current = { signature, id: randomId() }
      return ClassesService.createHelpRequest({
        code,
        requestBody: {
          request_id: request.current.id,
          category,
          text: text.trim(),
        },
      })
    },
    onSuccess: (result) => {
      if (identity.current !== localStorage.getItem("access_token")) return
      client.setQueryData(classroomMessagesKey(code), [
        result,
        ...(query.data ?? []).filter((row) => row.id !== result.id),
      ])
      invalidate()
      setText("")
      request.current = { signature: "", id: "" }
    },
  })
  const action = useMutation({
    mutationFn: ({
      id,
      action,
    }: {
      id: string
      action: "read" | "withdrawn"
    }) => {
      if (identity.current !== localStorage.getItem("access_token"))
        throw new Error("Session changed")
      return ClassesService.actOnClassMessage({ code, messageId: id, action })
    },
    onSuccess: invalidate,
  })
  const reminders = query.data?.filter((row) => row.kind === "reminder") ?? []
  return (
    <section
      aria-label={t({ zh: "课堂消息与求助", en: "Class messages and help" })}
      className="min-w-0 space-y-4 rounded-2xl border bg-card p-4 sm:p-5"
    >
      <h2 className="font-semibold">
        {t({ zh: "课堂消息与求助", en: "Class messages and help" })}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t({
          zh: "求助会发给本班老师，联网时通常在几秒内送达。考试计时会继续；老师的提醒需要你明确点击已读。",
          en: "Help goes to your classroom teacher, usually within seconds while online. Exam time keeps running. Mark reminders read yourself.",
        })}
      </p>
      {!active && lastResolvedHelp && (
        <p className="rounded-xl border p-3 text-sm" role="status">
          {lastResolvedHelp.resolution === "resolved"
            ? t({
                zh: "老师已将上次求助标记为处理完成；若仍有问题，可以再次求助。",
                en: "Your teacher marked your last request resolved. Ask again if you still need help.",
              })
            : t({
                zh: "上次求助已撤回。",
                en: "Your last help request was withdrawn.",
              })}
        </p>
      )}
      {query.isError ? (
        <Button
          variant="outline"
          className="min-h-11"
          onClick={() => void query.refetch()}
        >
          {t({ zh: "消息加载失败，重试", en: "Messages unavailable. Retry" })}
        </Button>
      ) : query.isPending ? (
        <p role="status">
          {t({ zh: "正在加载消息…", en: "Loading messages…" })}
        </p>
      ) : (
        <>
          {active ? (
            <div className="space-y-2 rounded-xl border p-3">
              <p className="font-medium">
                {active.read_at
                  ? t({
                      zh: "老师已查看，等待处理",
                      en: "Teacher has seen your request",
                    })
                  : t({
                      zh: "已向老师求助，等待查看",
                      en: "Help sent; waiting for your teacher",
                    })}
              </p>
              <p className="whitespace-pre-wrap break-words text-sm">
                {active.category && active.category in helpCategories
                  ? t(
                      helpCategories[
                        active.category as keyof typeof helpCategories
                      ],
                    )
                  : ""}
                {active.text && ` · ${active.text}`}
              </p>
              <Button
                variant="outline"
                className="min-h-11"
                disabled={action.isPending}
                onClick={() =>
                  action.mutate({ id: active.id, action: "withdrawn" })
                }
              >
                {t({
                  zh: "我已解决，撤回求助",
                  en: "I fixed it — withdraw request",
                })}
              </Button>
            </div>
          ) : (
            <fieldset disabled={help.isPending} className="min-w-0 space-y-3">
              <legend className="mb-2 font-medium">
                {t({ zh: "向老师举手求助", en: "Raise your hand for help" })}
              </legend>
              <label className="block space-y-2">
                <span>
                  {t({
                    zh: "需要什么帮助？",
                    en: "What do you need help with?",
                  })}
                </span>
                <select
                  aria-label={t({ zh: "求助类型", en: "Help category" })}
                  className="min-h-11 w-full rounded-md border bg-background px-3 text-base"
                  value={category}
                  onChange={(event) =>
                    setCategory(event.target.value as typeof category)
                  }
                >
                  {Object.entries(helpCategories).map(([key, label]) => (
                    <option key={key} value={key}>
                      {t(label)}
                    </option>
                  ))}
                </select>
              </label>
              <Textarea
                aria-label={t({
                  zh: "求助补充说明（可选）",
                  en: "More details (optional)",
                })}
                className="text-base"
                maxLength={500}
                value={text}
                onChange={(event) => setText(event.target.value)}
              />
              <Button className="min-h-11" onClick={() => help.mutate()}>
                {t({ zh: "发送求助", en: "Send help request" })}
              </Button>
            </fieldset>
          )}
          {reminders.length > 0 && (
            <div className="space-y-3">
              <h3 className="font-medium">
                {t({ zh: "老师的提醒", en: "Teacher reminders" })}
              </h3>
              {reminders.slice(0, shown).map((row) => (
                <article
                  className="space-y-2 rounded-xl border p-3"
                  key={row.id}
                >
                  <p className="whitespace-pre-wrap break-words">{row.text}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatDateTime(row.created_at, lang)}
                  </p>
                  {row.read_at ? (
                    <p className="text-sm">
                      {t({
                        zh: "你已标记为已读",
                        en: "You marked this as read",
                      })}
                    </p>
                  ) : (
                    <Button
                      variant="outline"
                      className="min-h-11"
                      disabled={action.isPending}
                      onClick={() =>
                        action.mutate({ id: row.id, action: "read" })
                      }
                    >
                      {t({ zh: "我已阅读", en: "Mark as read" })}
                    </Button>
                  )}
                </article>
              ))}
              {shown < reminders.length && (
                <Button
                  variant="outline"
                  className="min-h-11"
                  onClick={() => setShown((value) => value + 20)}
                >
                  {t({ zh: "更多提醒", en: "More reminders" })}
                </Button>
              )}
            </div>
          )}
        </>
      )}
      {help.isError && (
        <p role="alert" className="text-sm text-destructive">
          {help.error instanceof ApiError && help.error.status === 409
            ? t({
                zh: "已有待处理求助，请刷新查看。",
                en: "You already have an open request. Refresh to view it.",
              })
            : t({
                zh: "求助发送失败，内容已保留，请重试。",
                en: "Help request failed. Your text is kept; retry.",
              })}
        </p>
      )}
      {action.isError && (
        <p role="alert" className="text-sm text-destructive">
          {t({
            zh: "状态更新失败，请重试。",
            en: "Could not update the status. Retry.",
          })}
        </p>
      )}
    </section>
  )
}
