import { useMutation, useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { AttemptsService } from "@/client"

export interface AttemptSubmitTarget {
  itemType: "passage" | "repeat" | "question"
  itemId: string
  studentId?: string
  sessionId?: string
}

/**
 * 上传一条作答并轮询到 done/failed（PRD 不可协商 #4：上传与评分分离）。
 */
export function useAttemptSubmit(target: AttemptSubmitTarget) {
  const [attemptId, setAttemptId] = useState<string | null>(null)

  const submitMutation = useMutation({
    mutationFn: async (variables: { blob: Blob; duration: number }) => {
      const file = new File([variables.blob], "attempt.webm", {
        type: variables.blob.type || "audio/webm",
      })
      return AttemptsService.createAttemptUpload({
        formData: {
          // 生成器把 binary 类型标为 string，运行时传 File 均可
          audio: file as unknown as string,
          item_type: target.itemType,
          item_id: target.itemId,
          duration_s: Math.round(variables.duration * 10) / 10,
          ...(target.studentId ? { student_id: target.studentId } : {}),
          ...(target.sessionId ? { session_id: target.sessionId } : {}),
        },
      })
    },
    onSuccess: (data) => setAttemptId(data.id ?? null),
  })

  const attemptQuery = useQuery({
    queryKey: ["attempt", attemptId],
    queryFn: () =>
      AttemptsService.readAttempt({ attemptId: attemptId as string }),
    enabled: attemptId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === "done" || status === "failed" ? false : 2000
    },
  })

  const reset = () => setAttemptId(null)

  return {
    submit: submitMutation.mutate,
    submitting: submitMutation.isPending,
    submitError: submitMutation.isError,
    attempt: attemptId ? attemptQuery.data : undefined,
    reset,
  }
}
