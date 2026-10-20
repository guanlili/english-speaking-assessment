import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { ApiError, ClassesService } from "@/client"
import { pollWhileVisible } from "@/lib/poll"

const REVISION_REFRESH_MS = 5000

/** 首页保持与老师发布同步；仅版本变化时取完整题单，不触碰作答中的快照。 */
export function useClassroomRevision(
  code: string,
  studentId: string | undefined,
) {
  const client = useQueryClient()
  const previous = useRef<string | null>(null)
  const identity = `${code}:${studentId}`
  const query = useQuery({
    queryKey: ["classroom-revision", code, studentId],
    queryFn: () =>
      ClassesService.readClassroomRevision({ code: code.toUpperCase() }),
    enabled: Boolean(studentId),
    retry: 1,
    refetchInterval: pollWhileVisible((query) =>
      query.state.error instanceof ApiError &&
      [401, 403, 404].includes(query.state.error.status)
        ? false
        : REVISION_REFRESH_MS,
    ),
  })
  const revision = query.data?.revision
  useEffect(() => {
    if (!revision) return
    const next = `${identity}:${revision}`
    if (previous.current === next) return
    previous.current = next
    void client.invalidateQueries({
      queryKey: ["classroom", code, "today", studentId],
    })
    void client.invalidateQueries({
      queryKey: ["classroom", code, "path", studentId],
    })
  }, [client, code, studentId, identity, revision])
}
