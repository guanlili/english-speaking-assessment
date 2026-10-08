import type { ExamStatus } from "@/client"
import { ExamCountdownChip } from "@/components/Practice/ExamCountdowns"
import { useI18n } from "@/lib/i18n"

/** 顶部模考状态横幅：整场倒计时数字由 memo 化的 ExamCountdownChip 自行订阅。 */
export default function ExamBanner({
  exam,
  examEnded,
  examActive,
  syncedAt,
}: {
  exam: ExamStatus
  examEnded: boolean
  examActive: boolean
  syncedAt: number
}) {
  const { t } = useI18n()
  return (
    <div
      role="status"
      className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-3 ${
        examEnded
          ? "border-destructive/30 bg-destructive/5"
          : "border-orange-300/50 bg-orange-50 dark:bg-orange-950/30"
      }`}
    >
      <p className="text-sm font-semibold">
        {examEnded
          ? t({ zh: "考试已结束", en: "The exam has ended" })
          : t({ zh: "模考进行中", en: "Exam in progress" })}
        {examActive && <ExamCountdownChip exam={exam} syncedAt={syncedAt} />}
      </p>
      <p className="text-xs text-muted-foreground">
        {examEnded
          ? t({
              zh: "时间到已自动交卷，正在进入结果页…",
              en: "Time is up — auto-submitted. Opening results…",
            })
          : t({
              zh: "整场限时 · 每题只能作答一次 · 切屏会被记录",
              en: "Time-limited · one attempt per item · screen switches are recorded",
            })}
      </p>
    </div>
  )
}
