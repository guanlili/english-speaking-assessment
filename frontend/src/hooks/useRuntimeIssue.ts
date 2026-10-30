import { useEffect, useRef } from "react"
import { ClassesService, type RuntimeIssueIn } from "@/client"

/** Self-reported hints expire server-side. Never send error text or recordings. */
export function useRuntimeIssue(
  code: string,
  sessionId: string | undefined,
  issue: RuntimeIssueIn["issue"],
) {
  const identityToken = useRef(localStorage.getItem("access_token"))
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  useEffect(() => {
    if (!sessionId) return
    let disposed = false
    const report = () => {
      queue.current = queue.current.then(() => {
        if (
          disposed ||
          localStorage.getItem("access_token") !== identityToken.current
        )
          return
        return ClassesService.reportRuntimeIssue({
          code,
          runtimeIssueIn: { session_id: sessionId, issue },
        }).catch(() => {})
      })
    }
    report()
    if (!issue)
      return () => {
        disposed = true
      }
    const timer = setInterval(report, 60_000)
    window.addEventListener("online", report)
    return () => {
      disposed = true
      clearInterval(timer)
      window.removeEventListener("online", report)
    }
  }, [code, sessionId, issue])
}
