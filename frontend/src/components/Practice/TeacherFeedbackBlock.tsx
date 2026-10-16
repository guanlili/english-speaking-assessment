import type { AttemptPublic } from "@/client"
import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"

export function TeacherFeedbackBlock({
  attempt,
}: {
  attempt: Pick<
    AttemptPublic,
    | "teacher_feedback"
    | "teacher_focus"
    | "teacher_feedback_author"
    | "teacher_feedback_at"
  >
}) {
  const { t, lang } = useI18n()
  if (!attempt.teacher_feedback && !attempt.teacher_focus) return null
  return (
    <section
      className="space-y-2 rounded-xl border border-primary/20 bg-primary/5 p-4"
      aria-label={t({ zh: "教师点评", en: "Teacher feedback" })}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">
          {t({ zh: "教师点评", en: "Teacher feedback" })}
        </h3>
        {attempt.teacher_focus && (
          <Badge>{t({ zh: "重点关注", en: "Focus area" })}</Badge>
        )}
      </div>
      {attempt.teacher_feedback && (
        <p className="whitespace-pre-wrap break-words text-sm">
          {attempt.teacher_feedback}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        {attempt.teacher_feedback_author}
        {attempt.teacher_feedback_at &&
          ` · ${formatDateTime(attempt.teacher_feedback_at, lang)}`}
      </p>
      <p className="text-xs text-muted-foreground">
        {t({
          zh: "来自老师的教学建议，与 AI 参考反馈分开展示。",
          en: "Teaching advice from your teacher, separate from AI reference feedback.",
        })}
      </p>
    </section>
  )
}
