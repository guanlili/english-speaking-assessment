import { useMutation, useQuery } from "@tanstack/react-query"
import { useCallback, useRef, useState } from "react"
import { AttemptsService } from "@/client"

export interface AttemptSubmitTarget {
  itemType: "passage" | "repeat" | "question"
  itemId: string
  studentId?: string
  sessionId?: string
  idempotencyKey?: string
  token?: string
}

/**
 * 上传一条作答并轮询到 done/failed（PRD 不可协商 #4：上传与评分分离）。
 *
 * submit 接受可选的 targetOverride：录音开始时钉住 item_id / session_id / 题型，
 * 录音期间老师切换指派不会让旧录音提交到新题新轮。
 * idempotencyKey 确保重传不重复创建作答/扣费。
 * 返回 uploadError 区分上传失败（可重传）与评分失败。
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
          ...(t.studentId ? { student_id: t.studentId } : {}),
          ...(t.sessionId ? { session_id: t.sessionId } : {}),
          ...(t.idempotencyKey ? { idempotency_key: t.idempotencyKey } : {}),
          ...(t.token ? { token: t.token } : {}),
        },
      })
    },
    onSuccess: (data) => setAttemptId(data.id ?? null),
  })

  const attemptQuery = useQuery({
    queryKey: ["attempt", attemptId],
    queryFn: () =>
      AttemptsService.readAttempt({
        attemptId: attemptId as string,
        ...(targetRef.current.token ? { token: targetRef.current.token } : {}),
      }),
    enabled: attemptId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === "done" || status === "failed" ? false : 2000
    },
  })

  // useCallback：reset 会作为练习页自动推进 effect 的依赖，必须保持引用稳定
  const reset = useCallback(() => setAttemptId(null), [])

  return {
    submit: (
      variables: { blob: Blob; duration: number },
      targetOverride?: AttemptSubmitTarget,
    ) => submitMutation.mutate({ ...variables, targetOverride }),
    submitting: submitMutation.isPending,
    submitError: submitMutation.isError,
    submitErrorData: submitMutation.error as {
      status?: number
      body?: { detail?: string }
    } | null,
    attempt: attemptId ? attemptQuery.data : undefined,
    reset,
  }
}
