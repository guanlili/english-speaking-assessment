import assert from "node:assert/strict"
import test from "node:test"
import { QueryClient, QueryObserver } from "@tanstack/react-query"
import {
  ATTEMPT_POLL_MS,
  attemptPollIntervalMs,
  POLL_BACKOFF_MAX_MS,
  pollErrorInfo,
  RUBRIC_POLL_MS,
  rubricPending,
} from "../src/lib/attempt-polling.ts"

/**
 * 作答轮询节奏（批次08A / 返修R12）：
 * - 终态优先：done（rubric 非 pending）与 failed 即使伴随错误也停止，
 *   503 不能重启已停止的轮询；
 * - 真实网络错误（AxiosError ERR_NETWORK，status 为 undefined）必须
 *   进入退避——用 errorPresent 显式传递，不看 status 是否为 undefined；
 * - 403/404 不可重试即停；退避指数增长封顶，成功归零。
 */

test("评分中快速轮询，failed 停止（即使伴随错误）", () => {
  assert.equal(attemptPollIntervalMs({ status: "queued" }), ATTEMPT_POLL_MS)
  assert.equal(attemptPollIntervalMs({ status: "scoring" }), ATTEMPT_POLL_MS)
  assert.equal(attemptPollIntervalMs({ status: "failed" }), false)
  // 终态优先：failed + 503 不重启轮询
  assert.equal(
    attemptPollIntervalMs({
      status: "failed",
      errorPresent: true,
      errorStatus: 503,
    }),
    false,
  )
})

test("done 且 rubric pending：慢轮询不假死；其余 done 停止", () => {
  assert.equal(
    attemptPollIntervalMs({ status: "done", rubricStatus: "pending" }),
    RUBRIC_POLL_MS,
  )
  assert.equal(attemptPollIntervalMs({ status: "done" }), false)
  assert.equal(
    attemptPollIntervalMs({ status: "done", rubricStatus: "unavailable" }),
    false,
  )
  assert.equal(
    attemptPollIntervalMs({ status: "done", rubricStatus: null }),
    false,
  )
  // 终态优先：done（rubric 已出）后台刷新遇 503 不得重新轮询
  assert.equal(
    attemptPollIntervalMs({
      status: "done",
      rubricStatus: null,
      errorPresent: true,
      errorStatus: 503,
    }),
    false,
  )
})

test("403/404 不可重试：立即停止轮询", () => {
  assert.equal(
    attemptPollIntervalMs({ errorPresent: true, errorStatus: 403 }),
    false,
  )
  assert.equal(
    attemptPollIntervalMs({ errorPresent: true, errorStatus: 404 }),
    false,
  )
})

test("真实网络错误（status undefined）进入退避；错误期间挂起的 done 保持慢轮询退避", () => {
  // AxiosError ERR_NETWORK：code 存在但 status 为 undefined
  const networkError = Object.assign(new Error("Network Error"), {
    code: "ERR_NETWORK",
  })
  const info = pollErrorInfo(networkError)
  assert.equal(info.present, true)
  assert.equal(info.status, undefined)
  assert.equal(
    attemptPollIntervalMs({ errorPresent: true, errorStatus: undefined }),
    ATTEMPT_POLL_MS,
  )
  assert.equal(
    attemptPollIntervalMs({
      errorPresent: true,
      errorStatus: undefined,
      failureCount: 1,
    }),
    2000,
  )
})

test("网络退避指数增长封顶，成功后归零恢复快轮询", () => {
  assert.equal(
    attemptPollIntervalMs({ errorPresent: true, failureCount: 0 }),
    1000,
  )
  assert.equal(
    attemptPollIntervalMs({ errorPresent: true, failureCount: 2 }),
    4000,
  )
  assert.equal(
    attemptPollIntervalMs({ errorPresent: true, failureCount: 9 }),
    POLL_BACKOFF_MAX_MS,
  )
  assert.equal(
    attemptPollIntervalMs({ status: "scoring", failureCount: 9 }),
    ATTEMPT_POLL_MS,
  )
})

test("rubricPending 只在 done 且 pending 时为真", () => {
  assert.equal(
    rubricPending({ status: "done", rubric: { status: "pending" } }),
    true,
  )
  assert.equal(rubricPending({ status: "done", rubric: null }), false)
  assert.equal(
    rubricPending({ status: "done", rubric: { mock_score: 6 } }),
    false,
  )
  assert.equal(
    rubricPending({ status: "scoring", rubric: { status: "pending" } }),
    false,
  )
  assert.equal(rubricPending(undefined), false)
})

test("pollErrorInfo：null 无错误；数字状态码透传；非数字状态码视为纯网络错误", () => {
  assert.deepEqual(pollErrorInfo(null), { present: false, status: undefined })
  assert.deepEqual(pollErrorInfo(undefined), {
    present: false,
    status: undefined,
  })
  const httpError = Object.assign(new Error("503"), { status: 503 })
  assert.deepEqual(pollErrorInfo(httpError), { present: true, status: 503 })
})

/**
 * QueryObserver 级验证（返修R12）：连续失败→成功恢复期间，把观察到的
 * 真实 query 状态喂给轮询函数，断言退避增长、成功归零、GET 次数与
 * 终态不重启。
 */
test("QueryObserver：真实失败/恢复序列下的轮询决策与请求次数", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  let gets = 0
  let failuresLeft = 2
  const observer = new QueryObserver(client, {
    queryKey: ["attempt", "obs-test"],
    queryFn: () => {
      gets += 1
      if (failuresLeft > 0) {
        failuresLeft -= 1
        // 真实网络错误形态：code 存在、status 为 undefined
        throw Object.assign(new Error("Network Error"), {
          code: "ERR_NETWORK",
        })
      }
      return { status: "queued", rubric: null }
    },
  })

  // 订阅期间记录真实观察到的快照（错误形态 + 数据状态）
  const seen: Array<{ errorPresent: boolean; status?: string }> = []
  const unsubscribe = observer.subscribe((result) => {
    seen.push({
      errorPresent: pollErrorInfo(result.error).present,
      status: (result.data as { status?: string } | undefined)?.status,
    })
  })
  // 订阅触发第 1 次 fetch（失败）；retry:false 下失败不自动重试，
  // 由轮询循环显式重拉：第 2 次仍失败、第 3 次成功
  await new Promise((resolve) => setTimeout(resolve, 30))
  await observer.refetch()
  await observer.refetch()
  unsubscribe()

  const finalState = client.getQueryState(["attempt", "obs-test"])
  assert.equal(finalState?.status, "success")
  assert.equal(gets, 3) // 两次失败 + 一次成功；retry:false 下无隐形重试
  // 观察到过真实的无状态码错误（errorPresent=true 来自 ERR_NETWORK 形态）
  assert.ok(seen.some((s) => s.errorPresent))
  // hook 自维护连续失败计数：第 1/2 次失败 → 2s/4s 退避
  assert.equal(
    attemptPollIntervalMs({ errorPresent: true, failureCount: 1 }),
    2000,
  )
  assert.equal(
    attemptPollIntervalMs({ errorPresent: true, failureCount: 2 }),
    4000,
  )
  // 恢复：最新观察快照无错误 + queued → 回到 1s 快轮询；GET 恰好 3 次
  const last = seen[seen.length - 1]
  assert.equal(last.errorPresent, false)
  assert.equal(attemptPollIntervalMs({ status: last.status }), ATTEMPT_POLL_MS)
})
