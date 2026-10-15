import { useQuery } from "@tanstack/react-query"
import { ClassesService, type ExamRuntimeState, type TodayPlan } from "@/client"

export function useAutomatedExamState(code: string, initialPlan: TodayPlan) {
  const query = useQuery<ExamRuntimeState>({
    queryKey: ["automated-exam-state", code, initialPlan.session_id],
    queryFn: () =>
      ClassesService.readExamState({ code, sessionId: initialPlan.session_id }),
    initialData: {
      session_id: initialPlan.session_id,
      exam: initialPlan.exam!,
      submitted_item_ids: initialPlan.attempts.map((a) => a.item_id),
    },
    refetchInterval: (query) => {
      if (query.state.error) return 3000
      const exam = query.state.data?.exam
      return !exam?.started || exam.ended ? 3000 : 1000
    },
    retry: 1,
  })
  // 题面冻结于初始发布快照；状态响应不携带题文、评分、rubric 或激励。
  return { ...query, plan: { ...initialPlan, exam: query.data.exam } }
}
