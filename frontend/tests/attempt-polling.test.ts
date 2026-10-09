import assert from "node:assert/strict"
import test from "node:test"
import {
  ATTEMPT_POLL_MS,
  POLL_BACKOFF_MAX_MS,
  RUBRIC_POLL_MS,
  attemptPollIntervalMs,
  rubricPending,
} from "../src/lib/attempt-polling.ts"

/**
 * 作答轮询节奏（批次08A）：done+rubric.pending 不假死、终态即停、
 * 403/404 不可重试即停、网络错误有上限退避。
 */

test("评分中快速轮询，failed 停止", () => {
  assert.equal(attemptPollIntervalMs({ status: "queued" }), ATTEMPT_POLL_MS)
  assert.equal(attemptPollIntervalMs({ status: "scoring" }), ATTEMPT_POLL_MS)
  assert.equal(attemptPollIntervalMs({ status: "failed" }), false)
})

test("done 且 rubric pending：慢轮询不假死；rubric 出分/暂缺后停止", () => {
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
})

test("403/404 不可重试：立即停止轮询", () => {
  assert.equal(attemptPollIntervalMs({ errorStatus: 403 }), false)
  assert.equal(attemptPollIntervalMs({ errorStatus: 404 }), false)
})

test("网络异常：指数退避并封顶，恢复后回到正常节奏", () => {
  assert.equal(attemptPollIntervalMs({ errorStatus: 0, failureCount: 0 }), 1000)
  assert.equal(attemptPollIntervalMs({ errorStatus: 0, failureCount: 1 }), 2000)
  assert.equal(attemptPollIntervalMs({ errorStatus: 0, failureCount: 2 }), 4000)
  assert.equal(attemptPollIntervalMs({ errorStatus: 0, failureCount: 4 }), 16000 > POLL_BACKOFF_MAX_MS ? POLL_BACKOFF_MAX_MS : 16000)
  assert.equal(
    attemptPollIntervalMs({ errorStatus: 0, failureCount: 9 }),
    POLL_BACKOFF_MAX_MS,
  )
  // 无状态码（纯网络错误）同样退避
  assert.equal(attemptPollIntervalMs({ errorStatus: 0, failureCount: 3 }), 8000)
  // 错误恢复：数据正常后回到 1s
  assert.equal(attemptPollIntervalMs({ status: "scoring", failureCount: 3 }), ATTEMPT_POLL_MS)
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
