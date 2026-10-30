import { useQuery } from "@tanstack/react-query"
import { ClassesService } from "@/client"
export const classReviewKey = (code: string, exerciseId: string) =>
  ["teacher", "class-review", code, exerciseId] as const
export function useClassReview(
  code: string,
  exerciseId: string,
  enabled = true,
) {
  return useQuery({
    queryKey: classReviewKey(code, exerciseId),
    queryFn: () =>
      ClassesService.readClassReview({ code, exercise_id: exerciseId }),
    enabled: enabled && Boolean(exerciseId),
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
