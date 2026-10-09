/**
 * 作答轮询节奏（纯函数，wise-quarry-trout 批次08A）。
 *
 * 区分四种状态，避免「done 即停」的假死与无界重试：
 * - 评分中（queued/scoring）：1s 快轮询；
 * - done 且 rubric 仍 pending：详情阶段未完成，2s 继续轮询；
 * - done（rubric 已出/无 rubric）或 failed：终态，停止；
 * - 403/404 等不可重试错误：停止（权限/作答不存在不是等一会儿能好的）；
 *   网络异常：指数退避（1s→2s→…封顶 15s），恢复后自动回到正常节奏。
 */

export interface AttemptPollState {
  status?: string
  /** attempt.rubric.status（无 rubric 引擎为 null） */
  rubricStatus?: string | null
  /** 轮询请求失败的 HTTP 状态码（网络层错误无状态码） */
  errorStatus?: number
  /** 连续失败次数（退避计算用） */
  failureCount?: number
}

export const ATTEMPT_POLL_MS = 1000
export const RUBRIC_POLL_MS = 2000
export const POLL_BACKOFF_MAX_MS = 15000

export function attemptPollIntervalMs(state: AttemptPollState): number | false {
  if (state.errorStatus !== undefined) {
    if (state.errorStatus === 403 || state.errorStatus === 404) {
      return false
    }
    const failureCount = Math.max(0, state.failureCount ?? 0)
    return Math.min(
      POLL_BACKOFF_MAX_MS,
      ATTEMPT_POLL_MS * 2 ** Math.min(failureCount, 4),
    )
  }
  if (state.status === "failed") {
    return false
  }
  if (state.status === "done") {
    // 基础反馈已就绪、rubric 详情未完成：慢轮询直到出分或暂缺
    return state.rubricStatus === "pending" ? RUBRIC_POLL_MS : false
  }
  return ATTEMPT_POLL_MS
}

/** rubric 是否仍在等待（页面据此显示「模拟分评定中」而不是假死） */
export function rubricPending(
  attempt:
    | {
        status?: string
        rubric?: Record<string, unknown> | null
      }
    | undefined,
): boolean {
  if (!attempt || attempt.status !== "done") return false
  return attempt.rubric?.["status"] === "pending"
}
