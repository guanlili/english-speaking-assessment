import { useEffect, useState } from "react"
import type { ExamStatus } from "@/client"

/** 以服务器同步时刻为锚；后台标签页被节流后回来仍显示真实剩余时间。 */
export function useExamClock(exam: ExamStatus | null, syncedAt: number) {
  const [now, setNow] = useState(Date.now)
  const active = Boolean(exam?.started && !exam.ended)
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(timer)
  }, [active])
  const remaining = (seconds: number) =>
    Math.max(
      0,
      Math.ceil(seconds - (Math.max(now, syncedAt) - syncedAt) / 1000),
    )
  return {
    remaining: exam ? remaining(exam.remaining_seconds) : null,
    itemRemaining: exam ? remaining(exam.item_remaining_seconds ?? 0) : 0,
    prepRemaining: exam ? remaining(exam.prep_remaining_seconds ?? 0) : 0,
  }
}
