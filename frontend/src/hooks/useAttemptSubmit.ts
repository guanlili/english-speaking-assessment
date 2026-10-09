import { useMutation, useQuery } from "@tanstack/react-query"
import { useCallback, useRef, useState } from "react"
import { AttemptsService } from "@/client"
import {
  attemptPollIntervalMs,
  pollErrorInfo,
  rubricPending,
} from "@/lib/attempt-polling"

export interface AttemptSubmitTarget {
  itemType: "passage" | "repeat" | "question"
  itemId: string
  sessionId?: string
  idempotencyKey?: string
}

/**
 * 上传一条作答并轮询到终态（PRD 不可协商 #4：上传与评分分离）。
 *
 * 学生身份走登录 JWT（Authorization 头，SDK 自动注入）；
 * submit 接受可选的 targetOverride：录音开始时钉住 item_id / session_id / 题型，
 * 录音期间老师切换指派不会让旧录音提交到新题新轮。
 * idempotencyKey 确保重传不重复创建作答/扣费。
 * 返回 uploadError 区分上传失败（可重传）与评分失败。
 *
 * 轮询节奏（批次08A，见 lib/attempt-polling）：done 但 rubric 仍 pending
 * 时继续轮询不出假死；403/404 停止；网络异常有上限退避。刷新评分只
 * GET——不重传音频、不新增幂等键。
 */
export function useAttemptSubmit(target: AttemptSubmitTarget) {
  const [attemptId, setAttemptId] = useState<string | null>(null)
  const targetRef = useRef(target)
  targetRef.current = target

  const submitMutation = useMutation({
    mutationFn: async (variables: {
      blob: Blob
      duration: number
      targetOverride?: AttemptSubmitTarget
    }) => {
      const t = variables.targetOverride ?? targetRef.current
      const file = new File([variables.blob], "attempt.webm", {
        type: variables.blob.type || "audio/webm",
      })
      return AttemptsService.createAttemptUpload({
        formData: {
          audio: file as unknown as string,
          item_type: t.itemType,
          item_id: t.itemId,
          duration_s: Math.round(variables.duration * 10) / 10,
          ...(t.sessionId ? { session_id: t.sessionId } : {}),
          ...(t.idempotencyKey ? { idempotency_key: t.idempotencyKey } : {}),
        },
      })
    },
    onSuccess: (data) => setAttemptId(data.id ?? null),
  })

  // 连续轮询失败次数（成功归零）：Query 的 fetchFailureCount 语义与
  // 轮询轮次无关（内部重试也会累计），退避用自己的计数（返修R12）
  const pollFailuresRef = useRef(0)

  const attemptQuery = useQuery({
    queryKey: ["attempt", attemptId],
    queryFn: () =>
      AttemptsService.readAttempt({ attemptId: attemptId as string }),
    enabled: attemptId !== null,
    refetchInterval: (query) => {
      const data = query.state.data
      const errorInfo = pollErrorInfo(query.state.error)
      if (errorInfo.present) {
        pollFailuresRef.current += 1
      } else {
        pollFailuresRef.current = 0
      }
      const rubric = data?.rubric as Record<string, unknown> | null | undefined
      return attemptPollIntervalMs({
        status: data?.status,
        rubricStatus: (rubric?.["status"] as string | undefined) ?? null,
        errorPresent: errorInfo.present,
        errorStatus: errorInfo.status,
        failureCount: pollFailuresRef.current,
      })
    },
  })

  // 只读重试（GET）：轮询因网络/服务器错误停止或退避时由用户触发，
  // 绝不重传音频、不新增幂等键（返修A：08A 状态接线）
  const refetchAttempt = useCallback(() => {
    void attemptQuery.refetch()
  }, [attemptQuery])

  // useCallback：reset 会作为练习页自动推进 effect 的依赖，必须保持引用稳定
  const resetMutation = submitMutation.reset
  const reset = useCallback(() => {
    setAttemptId(null)
    resetMutation()
  }, [resetMutation])

  const attempt = attemptId ? attemptQuery.data : undefined
  const pollError = pollErrorInfo(attemptQuery.error)

  return {
    submit: (
      variables: { blob: Blob; duration: number },
      targetOverride?: AttemptSubmitTarget,
    ) => submitMutation.mutate({ ...variables, targetOverride }),
    submitAsync: (
      variables: { blob: Blob; duration: number },
      targetOverride?: AttemptSubmitTarget,
    ) => submitMutation.mutateAsync({ ...variables, targetOverride }),
    submitting: submitMutation.isPending,
    submitError: submitMutation.isError,
    submitErrorData: submitMutation.error as {
      status?: number
      body?: { detail?: string }
    } | null,
    attempt,
    /** rubric 详情仍在评定中（done 后模拟分未出） */
    rubricPending: rubricPending(attempt),
    /** 轮询失败信息（403/404 已停轮；网络错误退避中），present=false 无错误 */
    pollError,
    /** 用户触发的只读刷新（GET），用于停轮/退避后的恢复 */
    refetchAttempt,
    reset,
  }
}
