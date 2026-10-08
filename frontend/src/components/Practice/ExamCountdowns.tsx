/**
 * 考试倒计时展示组件（memo 化的叶子节点）。
 * 秒级数字在这里订阅考试时钟：心跳重渲染被限制在本组件内，
 * 不再拖动整个练习页（useExamClock 顶部注释有完整设计说明）。
 */
import { memo } from "react"
import type { ExamStatus } from "@/client"
import { Button } from "@/components/ui/button"
import { useExamClockValue } from "@/hooks/useExamClock"
import { useI18n } from "@/lib/i18n"
import { formatExamCountdown, formatSeconds } from "@/lib/time"

interface ClockProps {
  exam: ExamStatus
  syncedAt: number
}

/** 整场剩余时间（顶部「模考进行中」横幅里的 mm:ss） */
export const ExamCountdownChip = memo(function ExamCountdownChip({
  exam,
  syncedAt,
}: ClockProps) {
  const remaining = useExamClockValue(exam, syncedAt, (c) => c.remaining)
  return (
    <span className="ml-2 font-mono text-base tabular-nums">
      {formatExamCountdown(remaining ?? exam.remaining_seconds)}
    </span>
  )
})

/** 当前题倒计时（含 Part 2 准备阶段切换）；e2e 通过 data-testid 断言 */
export const ExamItemTimer = memo(function ExamItemTimer({
  exam,
  syncedAt,
}: ClockProps) {
  const { t } = useI18n()
  const prepRemaining = useExamClockValue(
    exam,
    syncedAt,
    (c) => c.prepRemaining,
  )
  const itemRemaining = useExamClockValue(
    exam,
    syncedAt,
    (c) => c.itemRemaining,
  )
  return (
    <div
      role="timer"
      data-testid="exam-item-timer"
      className="rounded-xl bg-secondary/60 px-4 py-3 text-sm"
    >
      {t({
        zh: prepRemaining > 0 ? "准备倒计时" : "本题倒计时",
        en:
          prepRemaining > 0
            ? "Preparation remaining"
            : "Time remaining for this item",
      })}{" "}
      <span className="font-mono text-lg font-bold tabular-nums">
        {formatSeconds(prepRemaining > 0 ? prepRemaining : itemRemaining)}
      </span>
      <p className="text-xs text-muted-foreground">
        {t({
          zh: "到时自动提交已录音并进入下一题；未录音则跳过",
          en: "At the deadline, your recording submits and the next item opens. Items without a recording are skipped.",
        })}
      </p>
    </div>
  )
})

/** 题目说明页的剩余秒数；到点后不渲染（与原条件渲染等价） */
export const ExamInstructionCountdown = memo(function ExamInstructionCountdown({
  exam,
  syncedAt,
}: ClockProps) {
  const itemRemaining = useExamClockValue(
    exam,
    syncedAt,
    (c) => c.itemRemaining,
  )
  if (itemRemaining <= 0) return null
  return (
    <p role="timer" className="font-mono text-lg font-bold tabular-nums">
      {formatSeconds(itemRemaining)}
    </p>
  )
})

/** Part 2 准备时间块的纯展示部分（练习模式由页面传入 state 秒数） */
export const PrepCountdownBlock = memo(function PrepCountdownBlock({
  secondsLeft,
  onSkip,
}: {
  secondsLeft: number
  onSkip?: () => void
}) {
  const { t } = useI18n()
  return (
    <div
      role="timer"
      className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-secondary/60 px-4 py-3"
    >
      <p className="text-sm">
        <span className="font-mono text-lg font-bold tabular-nums">
          {formatSeconds(secondsLeft)}
        </span>{" "}
        {t({
          zh: "· 准备时间：先想好要说的要点，不用开口",
          en: "· Prep time: plan your points, no need to speak yet",
        })}
      </p>
      {onSkip && (
        <Button variant="ghost" size="sm" onClick={onSkip}>
          {t({ zh: "跳过准备，直接开始", en: "Skip prep" })}
        </Button>
      )}
    </div>
  )
})

/** Part 2 准备时间块（模考模式：秒数来自考试时钟；结束后不渲染） */
export const ExamPrepCountdown = memo(function ExamPrepCountdown({
  exam,
  syncedAt,
}: ClockProps) {
  const prepRemaining = useExamClockValue(
    exam,
    syncedAt,
    (c) => c.prepRemaining,
  )
  if (prepRemaining <= 0) return null
  return <PrepCountdownBlock secondsLeft={prepRemaining} />
})
