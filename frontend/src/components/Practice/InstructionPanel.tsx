import { ArrowRight } from "lucide-react"
import type { ExamStatus } from "@/client"
import { ExamInstructionCountdown } from "@/components/Practice/ExamCountdowns"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

/**
 * 题目说明题的作答区：无录音，大「继续」按钮（触控目标 ≥44px）。
 * 模考中本页按秒数计时（倒计时数字由 memo 组件订阅），可提前继续。
 */
export default function InstructionPanel({
  suggestedSeconds,
  itemDone,
  ackPending,
  onContinue,
  exam,
  syncedAt,
  hint,
}: {
  suggestedSeconds: number | null
  itemDone: boolean
  ackPending: boolean
  onContinue: () => void
  exam: ExamStatus | null
  syncedAt: number
  hint: string
}) {
  const { t } = useI18n()
  return (
    <div className="flex flex-col items-center gap-3 border-t pt-6 text-center">
      <p className="text-xs text-muted-foreground">
        {t({
          zh: `建议停留 ${suggestedSeconds} 秒`,
          en: `Suggested ${suggestedSeconds}s on this page`,
        })}
      </p>
      {exam && <ExamInstructionCountdown exam={exam} syncedAt={syncedAt} />}
      <Button
        size="lg"
        className="min-h-11 px-10 text-base"
        disabled={itemDone || ackPending}
        onClick={onContinue}
      >
        {itemDone
          ? t({ zh: "已继续", en: "Continued" })
          : t({ zh: "继续 · 进入下一题", en: "Continue" })}
        <ArrowRight className="size-4" />
      </Button>
      <p className="text-xs text-muted-foreground">
        {exam
          ? t({
              zh: "模考中本页按秒数计时，可提前继续，到时自动翻页",
              en: "Timed in this exam — continue early or it advances automatically",
            })
          : hint}
      </p>
    </div>
  )
}
