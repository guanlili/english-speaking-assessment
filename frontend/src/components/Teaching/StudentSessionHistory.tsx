import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { ClassesService } from "@/client"
import { AttemptFeedbackDialog } from "@/components/Teaching/AttemptFeedbackDialog"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

export function StudentSessionHistory({
  code,
  studentId,
}: {
  code: string
  studentId: string
}) {
  const { t } = useI18n()
  const [attemptId, setAttemptId] = useState<string | null>(null)
  const query = useQuery({
    queryKey: ["teacher", "student-sessions", code, studentId],
    queryFn: () =>
      ClassesService.readStudentSessions({
        code: code.toUpperCase(),
        studentId,
      }),
  })
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">
        {t({ zh: "历史练习与考试反馈", en: "Practice and exam history" })}
      </h2>
      {query.isPending && <p>{t({ zh: "正在加载…", en: "Loading…" })}</p>}
      {query.isError && (
        <Button variant="outline" onClick={() => void query.refetch()}>
          {t({ zh: "加载失败，重试", en: "Loading failed. Retry" })}
        </Button>
      )}
      {query.data?.length === 0 && (
        <p>{t({ zh: "暂无历史记录。", en: "No history yet." })}</p>
      )}
      {query.data?.map((row) => (
        <article
          key={row.session_id}
          className="space-y-2 rounded-xl border p-4"
        >
          <p className="break-words font-medium">
            {row.session_date} ·{" "}
            {t(
              row.is_exam
                ? { zh: "考试", en: "Exam" }
                : { zh: "练习", en: "Practice" },
            )}{" "}
            · {row.title ?? t({ zh: "自主练习", en: "Self practice" })}
          </p>
          <p className="text-sm text-muted-foreground">
            {t({
              zh: `完成 ${row.done_count}/${row.total_count} 题 · 参考分 ${row.overall_avg ?? "–"}`,
              en: `${row.done_count}/${row.total_count} done · reference score ${row.overall_avg ?? "–"}`,
            })}
          </p>
          <div className="flex flex-wrap gap-2">
            {row.attempt_ids?.map((id, index) => (
              <Button
                key={id}
                variant="outline"
                className="min-h-11"
                onClick={() => setAttemptId(id)}
              >
                {t({
                  zh: `作答反馈 ${index + 1}`,
                  en: `Answer feedback ${index + 1}`,
                })}
              </Button>
            ))}
          </div>
        </article>
      ))}
      <AttemptFeedbackDialog
        attemptId={attemptId}
        open={attemptId !== null}
        onClose={() => setAttemptId(null)}
      />
    </section>
  )
}
