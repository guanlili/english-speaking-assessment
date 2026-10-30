import { useInfiniteQuery } from "@tanstack/react-query"
import { CalendarDays, FileText } from "lucide-react"
import { useState } from "react"
import { ClassesService } from "@/client"
import { AttemptFeedbackDialog } from "@/components/Teaching/AttemptFeedbackDialog"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

const HISTORY_PAGE_SIZE = 30

export function StudentSessionHistory({
  code,
  studentId,
}: {
  code: string
  studentId: string
}) {
  const { t } = useI18n()
  const [attemptId, setAttemptId] = useState<string | null>(null)
  const query = useInfiniteQuery({
    queryKey: ["teacher", "student-sessions", code, studentId],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      ClassesService.readStudentSessions({
        code: code.toUpperCase(),
        student_id: studentId,
        limit: HISTORY_PAGE_SIZE,
        offset: pageParam,
      }),
    getNextPageParam: (lastPage, _pages, lastOffset) =>
      lastPage.length === HISTORY_PAGE_SIZE
        ? lastOffset + HISTORY_PAGE_SIZE
        : undefined,
  })
  const rows = query.data?.pages.flat() ?? []
  return (
    <section className="space-y-4 rounded-2xl border border-primary/10 bg-card p-4 shadow-sm sm:p-6">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-primary">
        <CalendarDays className="size-5" />
        {t({ zh: "历史练习与考试反馈", en: "Practice and exam history" })}
      </h2>
      {query.isPending && <p>{t({ zh: "正在加载…", en: "Loading…" })}</p>}
      {query.isError && (
        <Button variant="outline" onClick={() => void query.refetch()}>
          {t({ zh: "加载失败，重试", en: "Loading failed. Retry" })}
        </Button>
      )}
      {query.isSuccess && rows.length === 0 && (
        <p>{t({ zh: "暂无历史记录。", en: "No history yet." })}</p>
      )}
      {rows.map((row) => (
        <article
          key={row.session_id}
          className="space-y-3 rounded-xl border border-primary/10 bg-muted/20 p-4 sm:p-5"
        >
          <p className="break-words font-medium">
            {row.session_date} ·{" "}
            {t(
              row.is_exam
                ? { zh: "考试", en: "Exam" }
                : { zh: "练习", en: "Practice" },
            )}{" "}
            · {row.title ?? t({ zh: "自主练习", en: "Self practice" })}
          </p>
          <p className="rounded-lg bg-primary/5 px-3 py-2 text-sm tabular-nums text-muted-foreground">
            {t({
              zh: `完成 ${row.done_count}/${row.total_count} 题 · 参考分 ${row.overall_avg ?? "–"}`,
              en: `${row.done_count}/${row.total_count} done · reference score ${row.overall_avg ?? "–"}`,
            })}
          </p>
          <div className="flex flex-wrap gap-2">
            {row.attempt_ids?.map((id, index) => (
              <Button
                key={id}
                variant="outline"
                className="min-h-11"
                onClick={() => setAttemptId(id)}
              >
                <FileText className="size-4" />
                {t({
                  zh: `作答反馈 ${index + 1}`,
                  en: `Answer feedback ${index + 1}`,
                })}
              </Button>
            ))}
          </div>
        </article>
      ))}
      {query.hasNextPage && (
        <Button
          variant="outline"
          className="min-h-11"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {t(
            query.isFetchingNextPage
              ? { zh: "正在加载…", en: "Loading…" }
              : { zh: "加载更早记录", en: "Load older sessions" },
          )}
        </Button>
      )}
      <AttemptFeedbackDialog
        attemptId={attemptId}
        open={attemptId !== null}
        onClose={() => setAttemptId(null)}
      />
    </section>
  )
}
