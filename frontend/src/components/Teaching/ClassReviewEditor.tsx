import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { ApiError, ClassesService } from "@/client"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { classReviewKey, useClassReview } from "@/hooks/useClassReview"
import { useI18n } from "@/lib/i18n"

export function ClassReviewEditor({
  code,
  exerciseId,
  attemptId,
  onDirtyChange,
}: {
  code: string
  exerciseId: string
  attemptId?: string
  onDirtyChange?: (value: boolean) => void
}) {
  const { t } = useI18n()
  const client = useQueryClient()
  const identity = useRef(localStorage.getItem("access_token"))
  const query = useClassReview(code, exerciseId)
  const [draft, setDraft] = useState<{
    text: string
    saved: string
    revision: number
  } | null>(null)
  const [savedNow, setSavedNow] = useState(false)
  const [reloadEpoch, setReloadEpoch] = useState(0)
  const loadedEpoch = useRef(-1)
  useEffect(() => {
    if (!query.data) return
    if (loadedEpoch.current === reloadEpoch) {
      const result = query.data
      setDraft((current) => {
        if (!current || current.text !== current.saved) return current
        const text = attemptId
          ? (result.notes?.[attemptId] ?? "")
          : (result.summary ?? "")
        return current.revision === result.revision && current.saved === text
          ? current
          : { text, saved: text, revision: result.revision ?? 0 }
      })
      return
    }
    loadedEpoch.current = reloadEpoch
    const text = attemptId
      ? (query.data.notes?.[attemptId] ?? "")
      : (query.data.summary ?? "")
    setDraft({ text, saved: text, revision: query.data.revision ?? 0 })
  }, [query.data, reloadEpoch, attemptId])
  const dirty = draft !== null && draft.text !== draft.saved
  useEffect(() => {
    onDirtyChange?.(dirty)
  }, [dirty, onDirtyChange])
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ""
    }
    window.addEventListener("beforeunload", warn)
    return () => window.removeEventListener("beforeunload", warn)
  }, [dirty])
  const mutation = useMutation({
    mutationFn: (action: "save" | "publish" | "withdraw") => {
      if (!draft || identity.current !== localStorage.getItem("access_token"))
        throw new Error("Session changed")
      if (action === "save")
        return ClassesService.saveClassReview({
          code,
          exerciseId,
          requestBody: {
            expected_revision: draft.revision,
            ...(attemptId
              ? { attempt_id: attemptId, note: draft.text }
              : { summary: draft.text }),
          },
        })
      const requestBody = { expected_revision: draft.revision }
      return action === "publish"
        ? ClassesService.publishClassReview({ code, exerciseId, requestBody })
        : ClassesService.withdrawClassReview({ code, exerciseId, requestBody })
    },
    onSuccess: (result) => {
      if (identity.current !== localStorage.getItem("access_token")) return
      const text = attemptId
        ? (result.notes?.[attemptId] ?? "")
        : (result.summary ?? "")
      setDraft({ text, saved: text, revision: result.revision ?? 0 })
      client.setQueryData(classReviewKey(code, exerciseId), result)
      void client.invalidateQueries({
        queryKey: ["student", "class-summaries", code],
      })
      setSavedNow(true)
    },
  })
  const conflict =
    mutation.error instanceof ApiError && mutation.error.status === 409
  async function reload() {
    if (
      dirty &&
      !window.confirm(
        t({
          zh: "放弃未保存的讲评修改并重新加载？",
          en: "Discard unsaved discussion edits and reload?",
        }),
      )
    )
      return
    const result = await query.refetch()
    if (result.data) {
      mutation.reset()
      loadedEpoch.current = -1
      setReloadEpoch((value) => value + 1)
    }
  }
  if (query.isPending || (!draft && !query.isError))
    return (
      <p role="status">
        {t({ zh: "正在加载已保存讲评…", en: "Loading saved discussion…" })}
      </p>
    )
  if (!draft)
    return (
      <Button
        variant="outline"
        className="min-h-11"
        onClick={() => void reload()}
      >
        {t({ zh: "讲评加载失败，重试", en: "Discussion unavailable. Retry" })}
      </Button>
    )
  return (
    <fieldset
      disabled={mutation.isPending}
      className="min-w-0 space-y-3 rounded-xl border p-4"
    >
      <legend className="px-1 font-medium">
        {attemptId
          ? t({
              zh: "亮点与下一步建议（仅教师可见）",
              en: "Strengths and next steps (teachers only)",
            })
          : t({ zh: "课堂小结草稿", en: "Class summary draft" })}
      </legend>
      <p className="text-sm text-muted-foreground">
        {attemptId
          ? t({
              zh: "保存到这份练习，重新打开仍可继续。不会自动发给学生。",
              en: "Saved with this practice for later discussion. Not automatically shared with students.",
            })
          : t({
              zh: "先保存，再明确发布给本班学生。更新草稿不会覆盖已发布的小结；请勿在小结中写入学生姓名或个人评价。",
              en: "Save first, then explicitly publish to this class. Draft edits do not change the published summary. Omit student names and personal assessments.",
            })}
      </p>
      <Textarea
        aria-label={
          attemptId
            ? t({ zh: "亮点与下一步建议", en: "Strengths and next steps" })
            : t({ zh: "课堂小结内容", en: "Class summary text" })
        }
        className="min-h-32 text-base"
        maxLength={4000}
        value={draft.text}
        onChange={(event) => {
          setDraft({ ...draft, text: event.target.value })
          setSavedNow(false)
        }}
      />
      {dirty && (
        <p role="status" className="text-sm">
          {t({ zh: "有未保存修改", en: "Unsaved edits" })}
        </p>
      )}
      {savedNow && !dirty && (
        <p role="status" className="text-sm">
          {t({ zh: "已保存到这份练习", en: "Saved with this practice" })}
        </p>
      )}
      {mutation.isError && (
        <div role="alert" className="space-y-2 text-sm text-destructive">
          <p>
            {conflict
              ? t({
                  zh: "讲评已在其他页面修改，当前编辑已保留。请重新加载后核对，避免覆盖。",
                  en: "Discussion changed elsewhere. Your edits are kept; reload and compare before saving.",
                })
              : t({
                  zh: "操作失败，编辑已保留，请重试。考试小结需要考试结束并归档后才能发布。",
                  en: "Action failed; edits are kept. Retry. Exam summaries require completion and archiving before publishing.",
                })}
          </p>
          {conflict && (
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() => void reload()}
            >
              {t({ zh: "重新加载讲评", en: "Reload discussion" })}
            </Button>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          disabled={!dirty || conflict}
          onClick={() => mutation.mutate("save")}
        >
          {t({ zh: "保存讲评", en: "Save discussion" })}
        </Button>
        {!attemptId && (
          <>
            <Button
              variant="outline"
              className="min-h-11"
              disabled={dirty || !draft.text.trim() || conflict}
              onClick={() => {
                if (
                  window.confirm(
                    t({
                      zh: "将已保存的小结发布给本班学生？",
                      en: "Publish the saved summary to this class?",
                    }),
                  )
                )
                  mutation.mutate("publish")
              }}
            >
              {t({ zh: "发布课堂小结", en: "Publish class summary" })}
            </Button>
            {query.data?.published_summary && (
              <Button
                variant="outline"
                className="min-h-11"
                disabled={dirty || conflict}
                onClick={() => {
                  if (
                    window.confirm(
                      t({
                        zh: "撤回学生端的小结？草稿仍会保留。",
                        en: "Withdraw the student summary? Your draft is kept.",
                      }),
                    )
                  )
                    mutation.mutate("withdraw")
                }}
              >
                {t({ zh: "撤回小结", en: "Withdraw summary" })}
              </Button>
            )}
          </>
        )}
      </div>
      {!attemptId && query.data?.published_summary && (
        <details className="text-sm">
          <summary className="min-h-11 cursor-pointer py-3">
            {t({
              zh: "查看学生当前可见小结",
              en: "View the summary visible to students",
            })}
          </summary>
          <p className="whitespace-pre-wrap break-words">
            {query.data.published_summary}
          </p>
        </details>
      )}
    </fieldset>
  )
}
