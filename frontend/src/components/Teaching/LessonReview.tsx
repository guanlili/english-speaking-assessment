import { useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { AttemptsService, type BoardStudent } from "@/client"
import AttemptAudio from "@/components/Practice/AttemptAudio"
import { ClassReviewEditor } from "@/components/Teaching/ClassReviewEditor"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"
export function LessonReview({
  students,
  isExam,
  code,
  exerciseId,
  onDirtyChange,
  compact = false,
}: {
  compact?: boolean
  code: string
  exerciseId?: string | null
  students: BoardStudent[]
  isExam: boolean
  onDirtyChange?: (dirty: boolean) => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [id, setId] = useState("")
  const [noteDirty, setNoteDirty] = useState(false)
  const [summaryDirty, setSummaryDirty] = useState(false)
  useEffect(() => {
    onDirtyChange?.(noteDirty || summaryDirty)
  }, [noteDirty, summaryDirty, onDirtyChange])
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange])
  // Omit names from both options and projected content; exam responses wait for hand-in.
  const candidates = students.flatMap((student, si) =>
    isExam && !student.exam_ended
      ? []
      : student.items.flatMap((item, ii) =>
          item.status === "done" && item.attempt_id
            ? [
                {
                  id: item.attempt_id,
                  label: t({
                    zh: `示例 ${si + 1} · 第 ${ii + 1} 题`,
                    en: `Example ${si + 1} · Item ${ii + 1}`,
                  }),
                },
              ]
            : [],
        ),
  )
  const selected = candidates.find((item) => item.id === id) ?? candidates[0]
  const query = useQuery({
    queryKey: ["lesson-review", selected?.id],
    queryFn: () => AttemptsService.readAttempt({ attemptId: selected!.id }),
    enabled: open && Boolean(selected),
  })
  return (
    <section className="space-y-3 rounded-2xl border bg-card p-5">
      <h2 className="font-semibold">
        {t({ zh: "课堂讲评", en: "Class discussion" })}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t({
          zh: "匿名展示典型作答，回听录音并记录亮点与下一步建议。考试作答需交卷后才可选。",
          en: "Discuss anonymous answers, listen back and note strengths and next steps. Exam answers are available only after hand-in.",
        })}
      </p>
      <Button
        className="min-h-11"
        disabled={!candidates.length || !exerciseId}
        onClick={() => setOpen(true)}
      >
        {t({ zh: "打开匿名讲评", en: "Open anonymous discussion" })}
      </Button>
      {exerciseId && (
        <details open={compact ? undefined : true}>
          <summary
            className={`min-h-11 cursor-pointer py-3 text-sm font-medium ${compact ? "" : "hidden"}`}
          >
            {t({
              zh: "课堂小结草稿与发布",
              en: "Draft and publish a class summary",
            })}
          </summary>
          <ClassReviewEditor
            key={exerciseId}
            code={code}
            exerciseId={exerciseId}
            onDirtyChange={setSummaryDirty}
          />
        </details>
      )}
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (
            !value &&
            noteDirty &&
            !window.confirm(
              t({
                zh: "放弃未保存的讲评笔记？",
                en: "Discard unsaved discussion notes?",
              }),
            )
          )
            return
          setNoteDirty(false)
          setOpen(value)
        }}
      >
        <DialogContent className="sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "匿名作答讲评", en: "Anonymous answer discussion" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "页面不展示姓名；声音和回答内容仍可能被同学识别。讲评笔记保存后可继续使用，仅授权教师可见。",
                en: "Names are hidden; voices and answer content may still be recognizable. Saved notes remain available to authorized teachers.",
              })}
            </DialogDescription>
          </DialogHeader>
          <label className="space-y-2">
            <span>{t({ zh: "选择示例", en: "Choose an example" })}</span>
            <select
              className="min-h-11 w-full rounded-md border bg-background px-3 text-base"
              value={selected?.id ?? ""}
              onChange={(event) => {
                if (
                  noteDirty &&
                  !window.confirm(
                    t({
                      zh: "放弃当前未保存的讲评笔记并切换示例？",
                      en: "Discard unsaved notes and switch examples?",
                    }),
                  )
                )
                  return
                setNoteDirty(false)
                setId(event.target.value)
              }}
            >
              {candidates.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {query.isPending && (
            <p role="status">{t({ zh: "正在加载…", en: "Loading…" })}</p>
          )}
          {query.isError && (
            <Button variant="outline" onClick={() => void query.refetch()}>
              {t({ zh: "加载失败，重试", en: "Loading failed. Retry" })}
            </Button>
          )}
          {query.data && (
            <div className="space-y-4">
              <p className="whitespace-pre-wrap break-words text-xl">
                {query.data.item_text}
              </p>
              <AttemptAudio attemptId={query.data.id} className="w-full" />
              <h3 className="font-semibold">
                {t({
                  zh: "AI 转写（可能有误）",
                  en: "AI transcript (may contain errors)",
                })}
              </h3>
              <p className="whitespace-pre-wrap break-words text-lg">
                {query.data.transcript ||
                  t({ zh: "暂无转写", en: "No transcript" })}
              </p>
              {exerciseId && (
                <ClassReviewEditor
                  key={query.data.id}
                  code={code}
                  exerciseId={exerciseId}
                  attemptId={query.data.id}
                  onDirtyChange={setNoteDirty}
                />
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </section>
  )
}
