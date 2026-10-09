import assert from "node:assert/strict"
import test from "node:test"
import {
  getExamClockSnapshot,
  subscribeExamClock,
} from "../src/hooks/useExamClock.ts"

/**
 * 渲染隔离验证：React useSyncExternalStore 的契约是「快照值不变
 * （Object.is）不重渲染」，因此页面级重渲染次数 === selector 快照的
 * 跳变次数。这里直接统计真实 250ms 心跳下各 selector 的跳变次数：
 * 布尔 selector（页面层）稳态零跳变、到期恰好一次；秒级 selector
 * （展示组件）约每秒一次——即页面从每秒 4 次重渲染降到稳态 0 次。
 */

type ClockExam = Parameters<typeof getExamClockSnapshot>[0]

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms))

/** 订阅心跳，逐 tick 计算快照并统计 selector 的跳变次数 */
async function countSelectorTransitions<T>(
  exam: ClockExam,
  select: (snapshot: ReturnType<typeof getExamClockSnapshot>) => T,
  durationMs: number,
): Promise<number> {
  const syncedAt = Date.now()
  let previous = select(getExamClockSnapshot(exam, syncedAt))
  let transitions = 0
  let settle: (() => void) | undefined
  const done = new Promise<void>((resolve) => {
    settle = resolve
  })
  const unsubscribe = subscribeExamClock(() => {
    const current = select(getExamClockSnapshot(exam, syncedAt))
    if (!Object.is(current, previous)) {
      transitions += 1
      previous = current
    }
  })
  const timer = setTimeout(() => settle?.(), durationMs)
  await done
  clearTimeout(timer)
  unsubscribe()
  return transitions
}

test("exam null has neutral snapshot and no expiry", () => {
  const snapshot = getExamClockSnapshot(null, Date.now())
  assert.equal(snapshot.remaining, null)
  assert.equal(snapshot.itemRemaining, 0)
  assert.equal(snapshot.prepRemaining, 0)
})

test("boolean page selector: zero transitions while time remains", async () => {
  const exam = {
    remaining_seconds: 3600,
    item_remaining_seconds: 300,
  } as ClockExam
  // 1.2 秒（约 4-5 个心跳）内「本题到点」布尔始终为 false：稳态页面零重渲染
  const transitions = await countSelectorTransitions(
    exam,
    (s) => s.itemRemaining === 0,
    1200,
  )
  assert.equal(transitions, 0)
})

test("boolean page selector: exactly one transition at expiry", async () => {
  const exam = {
    remaining_seconds: 3600,
    item_remaining_seconds: 1,
  } as ClockExam
  // 2.2 秒内 1 秒到期：false→true 恰好一次跳变，之后不再触发
  const transitions = await countSelectorTransitions(
    exam,
    (s) => s.itemRemaining === 0,
    2200,
  )
  assert.equal(transitions, 1)
})

test("seconds selector stays coarse-grained (display components only)", async () => {
  const exam = {
    remaining_seconds: 3600,
    item_remaining_seconds: 300,
  } as ClockExam
  // 1.2 秒内整数秒变化 ≤ 2 次：秒级重渲染只发生在叶子展示组件
  const transitions = await countSelectorTransitions(
    exam,
    (s) => s.itemRemaining,
    1200,
  )
  assert.ok(transitions <= 2)
})

test("clock math anchors to server sync time", () => {
  const syncedAt = Date.now() - 5000
  const snapshot = getExamClockSnapshot(
    { remaining_seconds: 100, item_remaining_seconds: 40 } as ClockExam,
    syncedAt,
  )
  // 同步后 5 秒：整场 100-5=95，本题 40-5=35（ceil 口径）
  assert.equal(snapshot.remaining, 95)
  assert.equal(snapshot.itemRemaining, 35)
})

test("ticker stops delivering after unsubscribe", async () => {
  let fired = 0
  const unsubscribe = subscribeExamClock(() => {
    fired += 1
  })
  await sleep(600)
  assert.ok(fired >= 1, "heartbeat should fire while subscribed")
  unsubscribe()
  const firedAtUnsubscribe = fired
  await sleep(600)
  assert.equal(fired, firedAtUnsubscribe)
})
