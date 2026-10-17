import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { ClassesService } from "@/client"
import AttemptAudio from "@/components/Practice/AttemptAudio"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
export function LearningReportCard({
  code,
  studentId,
}: {
  code: string
  studentId?: string
}) {
  const { t } = useI18n()
  const [days, setDays] = useState(7)
  const [exerciseId, setExerciseId] = useState("")
  const query = useQuery({
    queryKey: ["learning-report", code, studentId, days, exerciseId],
    queryFn: () =>
      ClassesService.readLearningReport({
        code,
        studentId,
        days,
        exerciseId: exerciseId || undefined,
      }),
  })
  const exercises = useQuery({
    queryKey: ["teacher", "exercises", code],
    queryFn: () => ClassesService.listClassroomExercises({ code }),
    enabled: Boolean(studentId),
  })
  const report = query.data
  return (
    <section className="learning-report space-y-4 rounded-2xl border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold">
          {t({ zh: "阶段学习报告", en: "Learning report" })}
        </h2>
        <Button
          variant="outline"
          className="min-h-11 print:hidden"
          disabled={!report}
          onClick={() => window.print()}
        >
          {t({ zh: "打印 / 保存 PDF", en: "Print / save PDF" })}
        </Button>
      </div>
      <div className="flex flex-wrap gap-3 print:hidden">
        <label className="space-x-2">
          <span>{t({ zh: "时间范围", en: "Period" })}</span>
          <select
            aria-label={t({ zh: "时间范围", en: "Period" })}
            className="min-h-11 rounded-md border bg-background px-3 text-base"
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
          >
            <option value={7}>
              {t({ zh: "最近 7 天", en: "Last 7 days" })}
            </option>
            <option value={30}>
              {t({ zh: "最近 30 天", en: "Last 30 days" })}
            </option>
            <option value={90}>
              {t({ zh: "最近 90 天", en: "Last 90 days" })}
            </option>
          </select>
        </label>
        {studentId && (
          <label className="min-w-0 space-x-2">
            <span>{t({ zh: "教学练习", en: "Practice" })}</span>
            <select
              aria-label={t({ zh: "教学练习", en: "Practice" })}
              className="min-h-11 max-w-full rounded-md border bg-background px-3 text-base"
              value={exerciseId}
              onChange={(event) => setExerciseId(event.target.value)}
            >
              <option value="">
                {t({ zh: "全部练习", en: "All practice" })}
              </option>
              {exercises.data?.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.title} · v{row.version_no}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {query.isPending && (
        <p role="status">
          {t({ zh: "正在生成报告…", en: "Preparing report…" })}
        </p>
      )}
      {query.isError && (
        <Button
          variant="outline"
          className="min-h-11"
          onClick={() => void query.refetch()}
        >
          {t({ zh: "报告加载失败，重试", en: "Report unavailable. Retry" })}
        </Button>
      )}
      {report && (
        <>
          <p className="break-words font-medium">
            {report.display_name} · {report.start_date} – {report.end_date}
          </p>
          <p>
            {t({
              zh: `${report.session_count} 轮练习 · 完成 ${report.completed_items}/${report.total_items} 题 · 开口 ${report.speaking_minutes} 分钟`,
              en: `${report.session_count} sessions · ${report.completed_items}/${report.total_items} items completed · ${report.speaking_minutes} speaking minutes`,
            })}
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <p>
              {t({
                zh: "跟读参考分均值",
                en: "Reading/repeat reference average",
              })}
              : {report.reading_avg ?? "—"}
            </p>
            <p>
              {t({ zh: "问答参考分均值", en: "Q&A reference average" })}:{" "}
              {report.question_avg ?? "—"}
            </p>
          </div>
          <p className="text-sm text-muted-foreground">
            {t({
              zh: "各题按最近一次已提交状态统计；评分中与失败不算完成。参考分不是官方成绩，未结束考试不进入报告。",
              en: "Counts use the latest submission per item; pending and failed answers are not complete. Reference scores are not official results. Unfinished exams are excluded.",
            })}
          </p>
          {report.has_active_exam && (
            <p>
              {t({
                zh: "部分考试尚未结束，结束后可刷新查看。",
                en: "Some exams are unfinished. Refresh after they end.",
              })}
            </p>
          )}
          <h3 className="font-medium">
            {t({
              zh: "代表性录音与教师建议",
              en: "Selected recordings and teacher feedback",
            })}
          </h3>
          {!report.answers.length && (
            <p>
              {t({
                zh: "本阶段暂无已出分作答。",
                en: "No scored answers in this period.",
              })}
            </p>
          )}
          {report.answers.map((answer) => (
            <article
              key={answer.attempt_id}
              className="min-w-0 space-y-2 rounded-xl border p-3"
            >
              <p className="break-words">{answer.item_text}</p>
              <AttemptAudio
                attemptId={answer.attempt_id}
                className="w-full print:hidden"
              />
              {answer.teacher_feedback && (
                <p className="whitespace-pre-wrap break-words text-sm">
                  {t({ zh: "教师建议", en: "Teacher feedback" })}:{" "}
                  {answer.teacher_feedback}
                </p>
              )}
            </article>
          ))}
          <p className="text-sm">
            {t({
              zh: "下一步：优先完成教师补练；回听一条录音，根据点评调整表达，再练同一道题并对比。",
              en: "Next: complete targeted practice, replay one recording, revise your wording using feedback and compare a new answer to the same item.",
            })}
          </p>
        </>
      )}
    </section>
  )
}
