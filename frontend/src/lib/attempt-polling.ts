/**
 * 作答轮询节奏（纯函数，wise-quarry-trout 批次08A / 返修R12）。
 *
 * 规则（终态优先于错误）：
 * - failed、done 且 rubric 不再 pending：终态，停止——即使最近一次后台
 *   刷新失败（如 503）也不得把已停止的轮询重新启动；
 * - 评分中（queued/scoring）：1s 快轮询；done 且 rubric pending：2s 慢轮询；
 * - 403/404 不可重试：立即停止（权限/作答消失不是等一会儿能好的）；
 * - 其它错误（真实网络错误的 HTTP status 是 undefined，必须用
 *   errorPresent 显式传递，不能拿 status 是否为 undefined 判断）：
 *   指数退避 1s→2s→…封顶 15s。
 *
 * failureCount 由调用方自己维护（连续轮询失败次数，成功归零）——
 * TanStack Query 的 fetchFailureCount 语义与我们的轮询轮次无关，
 * 不能直接当作跨轮连续失败计数。
 */

export interface AttemptPollState {
  status?: string
  /** attempt.rubric.status（无 rubric 引擎为 null） */
  rubricStatus?: string | null
  /** 最新一轮刷新是否存在错误（与 HTTP 状态码无关的独立标志） */
  errorPresent?: boolean
  /** 错误的 HTTP 状态码；纯网络错误（AxiosError ERR_NETWORK）为 undefined */
  errorStatus?: number
  /** 连续失败次数（调用方维护，成功归零） */
  failureCount?: number
}

export const ATTEMPT_POLL_MS = 1000
export const RUBRIC_POLL_MS = 2000
export const POLL_BACKOFF_MAX_MS = 15000

/** 从任意错误对象提取轮询所需信息（真实 AxiosError 的 status 可能是 undefined） */
export function pollErrorInfo(error: unknown): {
  present: boolean
  status: number | undefined
} {
  if (error == null) return { present: false, status: undefined }
  const status = (error as { status?: unknown }).status
  return {
    present: true,
    status: typeof status === "number" ? status : undefined,
  }
}

export function attemptPollIntervalMs(state: AttemptPollState): number | false {
  // 终态优先：已完成/失败的作答，后台刷新失败也不重启轮询
  if (state.status === "failed") {
    return false
  }
  if (state.status === "done" && state.rubricStatus !== "pending") {
    return false
  }
  if (state.errorPresent) {
    if (state.errorStatus === 403 || state.errorStatus === 404) {
      return false
    }
    const failureCount = Math.max(0, state.failureCount ?? 0)
    return Math.min(
      POLL_BACKOFF_MAX_MS,
      ATTEMPT_POLL_MS * 2 ** Math.min(failureCount, 4),
    )
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
  if (attempt?.status !== "done") return false
  return attempt.rubric?.status === "pending"
}
