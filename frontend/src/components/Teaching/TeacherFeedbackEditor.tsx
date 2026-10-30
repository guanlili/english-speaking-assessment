import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { ApiError, type AttemptPublic, AttemptsService } from "@/client"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useI18n } from "@/lib/i18n"

export function TeacherFeedbackEditor({
  attempt,
  reload,
}: {
  attempt: AttemptPublic
  reload: () => void
}) {
  const { t } = useI18n()
  const client = useQueryClient()
  const identity = useRef(localStorage.getItem("access_token"))
  const [text, setText] = useState(attempt.teacher_feedback ?? "")
  const [tags, setTags] = useState<
    Array<"transcript_error" | "advice_unsuitable" | "reviewed">
  >(
    (attempt.teacher_review_tags ?? []).filter(
      (tag): tag is "transcript_error" | "advice_unsuitable" | "reviewed" =>
        ["transcript_error", "advice_unsuitable", "reviewed"].includes(tag),
    ),
  )
  const [focus, setFocus] = useState(attempt.teacher_focus ?? false)
  const save = useMutation({
    mutationFn: () => {
      if (localStorage.getItem("access_token") !== identity.current)
        throw new Error("Session changed")
      return AttemptsService.writeTeacherFeedback({
        attempt_id: attempt.id,
        teacherFeedbackWrite: {
          text,
          review_tags: tags,
          focus,
          expected_revision: attempt.teacher_feedback_revision ?? 0,
        },
      })
    },
    onSuccess: (value) => {
      if (localStorage.getItem("access_token") !== identity.current) return
      toast.success(t({ zh: "教师点评已保存", en: "Teacher feedback saved" }))
      client.setQueryData(["attempt-detail", attempt.id], value)
      void client.invalidateQueries({ queryKey: ["teacher", "board"] })
      void client.invalidateQueries({
        predicate: (query) => query.queryKey.includes(attempt.id),
      })
    },
  })
  const conflict = save.error instanceof ApiError && save.error.status === 409
  return (
    <fieldset
      disabled={save.isPending}
      className="min-w-0 space-y-3 rounded-xl border p-4"
    >
      <legend className="px-1 font-semibold">
        {t({ zh: "编辑教师点评", en: "Edit teacher feedback" })}
      </legend>
      <p className="text-sm text-muted-foreground">
        {t({
          zh: "保存后学生可回看；考试进行中不会向学生显示。清空文字并取消重点标记可移除点评。",
          en: "Students can review saved feedback after the exam ends. Clear the text and focus mark to remove feedback.",
        })}
      </p>
      <div className="flex flex-wrap gap-3">
        {(["reviewed", "transcript_error", "advice_unsuitable"] as const).map(
          (tag) => (
            <label
              key={tag}
              className="flex min-h-11 items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                className="size-5"
                checked={tags.includes(tag)}
                onChange={() =>
                  setTags(
                    tags.includes(tag)
                      ? tags.filter((value) => value !== tag)
                      : [...tags, tag],
                  )
                }
              />
              {t(
                tag === "reviewed"
                  ? { zh: "已由教师复核", en: "Reviewed by teacher" }
                  : tag === "transcript_error"
                    ? { zh: "AI 转写有误", en: "AI transcript has errors" }
                    : { zh: "AI 建议不适用", en: "AI advice unsuitable" },
              )}
            </label>
          ),
        )}
      </div>
      <Textarea
        aria-label={t({ zh: "教师点评内容", en: "Teacher feedback text" })}
        className="min-h-28 text-base"
        maxLength={4000}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <label className="flex min-h-11 items-center gap-3 text-sm">
        <input
          className="size-5"
          type="checkbox"
          checked={focus}
          onChange={(event) => setFocus(event.target.checked)}
        />
        {t({ zh: "标记为重点关注", en: "Mark as a focus area" })}
      </label>
      {save.isError && (
        <div role="alert" className="text-sm text-destructive">
          {t(
            conflict
              ? {
                  zh: "点评已被其他页面修改，当前文字尚未保存。重新加载会放弃当前编辑。",
                  en: "Feedback changed elsewhere. Your text is unsaved; reloading discards these edits.",
                }
              : {
                  zh: "保存失败，内容已保留，请重试。",
                  en: "Save failed. Your text is kept; retry.",
                },
          )}
          {conflict && (
            <Button
              variant="outline"
              className="ml-2 min-h-11"
              onClick={() => {
                if (
                  window.confirm(
                    t({
                      zh: "放弃未保存编辑并重新加载？",
                      en: "Discard unsaved edits and reload?",
                    }),
                  )
                )
                  reload()
              }}
            >
              {t({ zh: "重新加载点评", en: "Reload feedback" })}
            </Button>
          )}
        </div>
      )}
      <Button
        className="min-h-11"
        disabled={conflict || save.isPending}
        onClick={() => save.mutate()}
      >
        {t({ zh: "保存教师点评", en: "Save teacher feedback" })}
      </Button>
    </fieldset>
  )
}
