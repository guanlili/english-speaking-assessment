import { Shield } from "lucide-react"
import type { ExamStatus } from "@/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"

/** 模考开考确认页：计时以显式确认为准（服务端落时间），防止误触打开即烧时间。 */
export default function ExamStartConfirm({
  exam,
  startPending,
  onStart,
}: {
  exam: ExamStatus
  startPending: boolean
  onStart: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4">
      <Card className="w-full max-w-md">
        <CardContent className="space-y-5 pt-6 text-center">
          <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-orange-100 dark:bg-orange-950/40">
            <Shield className="size-6 text-orange-600" aria-hidden />
          </div>
          <div className="space-y-1">
            <h1 className="text-lg font-bold">
              {t({ zh: "准备开始考试", en: "Ready to start the exam" })}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t({
                zh: `本场考试整场限时 ${exam.time_limit_minutes} 分钟，点「开始考试」后即开始计时。`,
                en: `This exam is limited to ${exam.time_limit_minutes} minutes in total. Timing starts when you tap "Start exam".`,
              })}
            </p>
          </div>
          <ul className="mx-auto max-w-xs space-y-2 text-left text-sm text-muted-foreground">
            <li>
              {t({
                zh: "· 每题只能作答一次，题目出现后计时，到时自动进入下一题；未录音则记为未作答",
                en: "· One attempt per item. Timing starts when each item appears; it advances automatically at the deadline. Items without a recording remain unanswered.",
              })}
            </li>
            <li>
              {t({
                zh: "· 考试中切屏会被记录，老师可见",
                en: "· Screen switches during the exam are recorded and visible to your teacher",
              })}
            </li>
            <li>
              {t({
                zh: "· 时间一到将自动交卷并进入结果页",
                en: "· When time is up, the exam auto-submits and opens your results",
              })}
            </li>
          </ul>
          <Button
            className="min-h-11 w-full text-base"
            disabled={startPending}
            onClick={onStart}
          >
            {startPending
              ? t({ zh: "正在开始…", en: "Starting…" })
              : t({ zh: "开始考试", en: "Start exam" })}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
