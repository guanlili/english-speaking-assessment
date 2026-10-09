import { useCallback, useRef, useSyncExternalStore } from "react"
import type { ExamStatus } from "@/client"

/**
 * 考试时钟：以服务器同步时刻（query dataUpdatedAt）为锚计算真实剩余秒数，
 * 后台标签页被节流后回来仍显示真实剩余。
 *
 * 渲染隔离设计：250ms 心跳放在模块级 store 里，订阅方通过
 * useSyncExternalStore 按 selector 取「原始类型快照」——快照值不变
 * （Object.is）就不触发重渲染。因此：
 * - 页面层只允许选布尔（到点/未到点跳变），稳态零重渲染；
 * - 秒级倒计时数字只下沉到 memo 化的展示组件里订阅，
 *   避免 250ms 心跳把整页拖着重渲染（此前每秒 4 次）。
 */

export interface ExamClockSnapshot {
  /** 整场剩余秒；无考试为 null */
  remaining: number | null
  /** 当前题剩余秒 */
  itemRemaining: number
  /** 当前题准备阶段剩余秒 */
  prepRemaining: number
}

type Listener = () => void

const listeners = new Set<Listener>()
let ticker: ReturnType<typeof setInterval> | null = null

function startTicker() {
  if (ticker !== null) return
  ticker = setInterval(() => {
    for (const listener of listeners) listener()
  }, 250)
}

function stopTicker() {
  if (ticker !== null && listeners.size === 0) {
    clearInterval(ticker)
    ticker = null
  }
}

/** useSyncExternalStore 的 subscribe：引用计数，无人订阅时心跳归零。 */
export function subscribeExamClock(listener: Listener): () => void {
  listeners.add(listener)
  startTicker()
  return () => {
    listeners.delete(listener)
    stopTicker()
  }
}

function remainingSeconds(base: number, syncedAt: number): number {
  const now = Math.max(Date.now(), syncedAt)
  return Math.max(0, Math.ceil(base - (now - syncedAt) / 1000))
}

/** 纯计算：给定考试状态与同步时刻，派生三种剩余秒数。 */
export function getExamClockSnapshot(
  exam: ExamStatus | null,
  syncedAt: number,
): ExamClockSnapshot {
  if (!exam) {
    return { remaining: null, itemRemaining: 0, prepRemaining: 0 }
  }
  return {
    remaining: remainingSeconds(exam.remaining_seconds, syncedAt),
    itemRemaining: remainingSeconds(exam.item_remaining_seconds ?? 0, syncedAt),
    prepRemaining: remainingSeconds(exam.prep_remaining_seconds ?? 0, syncedAt),
  }
}

/**
 * 订阅考试时钟派生值。selector 必须返回原始类型（number/boolean/null），
 * 值不变不触发渲染；页面层请只选布尔，秒级数字留给展示组件。
 */
export function useExamClockValue<T extends number | boolean | null>(
  exam: ExamStatus | null,
  syncedAt: number,
  select: (clock: ExamClockSnapshot) => T,
): T {
  const latest = useRef({ exam, syncedAt, select })
  latest.current = { exam, syncedAt, select }
  const getSnapshot = useCallback(() => {
    const { exam, syncedAt, select } = latest.current
    return select(getExamClockSnapshot(exam, syncedAt))
  }, [])
  return useSyncExternalStore(subscribeExamClock, getSnapshot)
}
