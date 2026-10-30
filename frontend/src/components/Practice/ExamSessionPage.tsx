import { useQuery } from "@tanstack/react-query"
import { useParams, useSearch } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { ClassesService } from "@/client"
import AutomatedExamSession from "@/components/Practice/AutomatedExamSession"
import { PracticeSessionPage } from "@/components/Practice/PracticeSessionPage"
import { useStudentGuard } from "@/hooks/useStudentGuard"
import { loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"

export function ExamSessionPage() {
  const { code } = useParams({ strict: false }) as { code: string }
  const search = useSearch({ strict: false })
  const student = loadStudent(code)
  const { t } = useI18n()
  const storageKey = `exam-session:${student?.id}:${code.toUpperCase()}`
  const [pinnedSessionId, setPinnedSessionId] = useState(
    () => search.session ?? localStorage.getItem(storageKey) ?? undefined,
  )
  const sessionId = search.session ?? pinnedSessionId
  const query = useQuery({
    queryKey: ["exam-entry", code, student?.id, sessionId],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        session_id: sessionId,
      }),
    enabled: !!student,
    retry: 1,
    placeholderData: (previous) => previous,
  })
  useEffect(() => {
    if (!sessionId && query.data?.exam?.automated)
      setPinnedSessionId(query.data.session_id)
  }, [sessionId, query.data])
  useStudentGuard(code, student, query)
  if (query.isError)
    return (
      <div className="p-6">
        <p role="alert">
          {t({
            zh: "考试加载失败，请重试",
            en: "Could not load the exam. Please retry.",
          })}
        </p>
        <button
          type="button"
          className="min-h-11"
          onClick={() => void query.refetch()}
        >
          {t({ zh: "重试", en: "Retry" })}
        </button>
      </div>
    )
  if (!query.data)
    return <p className="p-6">{t({ zh: "加载中…", en: "Loading…" })}</p>
  return query.data.exam?.automated ? (
    <AutomatedExamSession
      key={query.data.session_id}
      code={code.toUpperCase()}
      initialPlan={query.data}
      storageKey={storageKey}
    />
  ) : (
    <PracticeSessionPage mode="exam" />
  )
}
