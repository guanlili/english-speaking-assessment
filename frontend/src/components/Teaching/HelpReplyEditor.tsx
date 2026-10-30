import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { ClassesService, type ClassMessagePublic } from "@/client"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useI18n } from "@/lib/i18n"

export function HelpReplyEditor({
  code,
  message,
}: {
  code: string
  message: ClassMessagePublic
}) {
  const { t } = useI18n()
  const client = useQueryClient()
  const [text, setText] = useState(message.reply_text ?? "")
  const [resolve, setResolve] = useState(true)
  const revision = useRef(message.reply_revision ?? 0)
  const identity = useRef(localStorage.getItem("access_token"))
  const reply = useMutation({
    mutationFn: () => {
      if (identity.current !== localStorage.getItem("access_token"))
        throw new Error("Session changed")
      return ClassesService.replyToClassHelp({
        code,
        message_id: message.id,
        helpReplyWrite: {
          text: text.trim(),
          resolve,
          expected_revision: revision.current,
        },
      })
    },
    onSuccess: (result) => {
      if (identity.current !== localStorage.getItem("access_token")) return
      revision.current = result.reply_revision ?? 0
      void client.invalidateQueries({
        queryKey: ["teacher", "class-messages", code],
      })
      void client.invalidateQueries({
        queryKey: ["student", "class-messages", code],
      })
    },
  })
  return (
    <details>
      <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">
        {t({ zh: "答复学生", en: "Reply to student" })}
      </summary>
      <fieldset disabled={reply.isPending} className="min-w-0 space-y-3">
        <Textarea
          className="text-base"
          maxLength={500}
          aria-label={t({ zh: "给学生的答复", en: "Reply text" })}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-5"
            checked={resolve}
            onChange={(event) => setResolve(event.target.checked)}
          />
          {t({ zh: "答复后标记处理完成", en: "Resolve after replying" })}
        </label>
        <Button
          className="min-h-11"
          disabled={!text.trim()}
          onClick={() => reply.mutate()}
        >
          {t({ zh: "发送答复", en: "Send reply" })}
        </Button>
        {reply.isSuccess && (
          <p role="status" className="text-sm">
            {t({
              zh: "答复已保存，学生可以查看。",
              en: "Reply saved and available to the student.",
            })}
          </p>
        )}
        {reply.isError && (
          <p role="alert" className="text-sm text-destructive">
            {t({
              zh: "答复失败，内容已保留。若其他窗口已修改，请复制当前答复后重新打开。",
              en: "Reply failed; your text is kept. If another window changed this request, copy your text and reopen.",
            })}
          </p>
        )}
      </fieldset>
    </details>
  )
}
