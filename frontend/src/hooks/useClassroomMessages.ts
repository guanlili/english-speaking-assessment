import { useQuery } from "@tanstack/react-query"
import { ClassesService } from "@/client"
export const classroomMessagesKey = (code: string) =>
  ["student", "class-messages", code] as const
export function useClassroomMessages(code: string) {
  return useQuery({
    queryKey: classroomMessagesKey(code),
    queryFn: async () => {
      const rows = await ClassesService.readMyClassMessages({
        code,
        limit: 100,
      })
      if (!Array.isArray(rows))
        throw new Error("Invalid class message response")
      return rows
    },
    enabled: Boolean(code),
    refetchInterval: 15000,
    retry: 1,
  })
}
export function usePublishedClassSummaries(code: string, offset: number) {
  return useQuery({
    queryKey: ["student", "class-summaries", code, offset],
    queryFn: async () => {
      const rows = await ClassesService.readPublishedClassSummaries({
        code,
        offset,
        limit: 11,
      })
      if (!Array.isArray(rows))
        throw new Error("Invalid class summary response")
      return rows
    },
    enabled: Boolean(code),
    refetchInterval: 30000,
    retry: 1,
  })
}
