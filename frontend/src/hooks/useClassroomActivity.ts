import { useEffect, useRef } from "react"
import { ClassesService, type ClassroomActivityIn } from "@/client"

export function useClassroomActivity(
  code: string,
  activity: ClassroomActivityIn["activity"],
  sessionId?: string,
) {
  const identity = useRef(localStorage.getItem("access_token"))
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  useEffect(() => {
    let disposed = false
    const report = () => {
      if (document.visibilityState === "hidden") return
      queue.current = queue.current
        .catch(() => {})
        .then(() => {
          if (
            disposed ||
            identity.current !== localStorage.getItem("access_token")
          )
            return
          return ClassesService.reportClassroomActivity({
            code,
            requestBody: { activity, session_id: sessionId },
          }).catch(() => {})
        })
    }
    report()
    const timer = window.setInterval(report, 30000)
    window.addEventListener("online", report)
    document.addEventListener("visibilitychange", report)
    return () => {
      disposed = true
      clearInterval(timer)
      window.removeEventListener("online", report)
      document.removeEventListener("visibilitychange", report)
    }
  }, [code, activity, sessionId])
}
