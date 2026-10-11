import { useQueries } from "@tanstack/react-query"
import { AttemptsService, type BoardItem } from "@/client"
import { RubricBlock } from "@/components/Practice/FeedbackCard"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"
import { ITEM_TYPE_LABELS } from "@/lib/terms"

/** Aggregate the actual latest attempts supplied by this publish/session row. */
export function StudentFeedbackDialog({
  name,
  items,
  open,
  onClose,
}: {
  name: string
  items: BoardItem[]
  open: boolean
  onClose: () => void
}) {
  const { t } = useI18n()
  const questions = items.filter((item) => item.type !== "instruction")
  const submitted = questions.filter((item) => item.attempt_id)
  const queries = useQueries({
    queries: submitted.map((item) => ({
      queryKey: ["attempt-detail", item.attempt_id],
      queryFn: () =>
        AttemptsService.readAttempt({ attemptId: item.attempt_id! }),
      enabled: open,
      retry: 1,
      refetchInterval: (query: {
        state: {
          data?: { status: string; rubric?: Record<string, unknown> | null }
        }
      }) => {
        const attempt = query.state.data
        return attempt &&
          (attempt.status === "queued" ||
            attempt.status === "scoring" ||
            attempt.rubric?.status === "pending")
          ? 3000
          : false
      },
    })),
  })
  const scores = queries.flatMap((query) =>
    query.data?.status === "done" && query.data.overall != null
      ? [query.data.overall]
      : [],
  )
  const doneCount = queries.filter(
    (query) => query.data?.status === "done",
  ).length
  const average = scores.length
    ? Math.round(
        (scores.reduce((sum, value) => sum + value, 0) / scores.length) * 10,
      ) / 10
    : "–"
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose()
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {t({ zh: `${name} · 汇总反馈`, en: `${name} · Overall feedback` })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "本条记录的实际 AI 反馈；参考分为已评分题目均值。",
              en: "Actual AI feedback for this record; the reference score averages scored items.",
            })}
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm">
          {t({
            zh: `已评分 ${doneCount}/${questions.length} 题 · 参考分 ${average}`,
            en: `${doneCount}/${questions.length} items scored · reference score ${average}`,
          })}
        </p>
        {submitted.length === 0 && (
          <p>
            {t({
              zh: "这条记录暂无作答反馈。",
              en: "No answer feedback for this record yet.",
            })}
          </p>
        )}
        {questions.map((item, index) => {
          const query =
            queries[
              submitted.findIndex((entry) => entry.item_id === item.item_id)
            ]
          const attempt = query?.data
          return (
            <section
              key={item.item_id}
              className="space-y-2 rounded-xl border p-4"
            >
              <h3 className="font-medium">
                {index + 1}.{" "}
                {t(
                  ITEM_TYPE_LABELS[item.type] ?? {
                    zh: item.type,
                    en: item.type,
                  },
                )}
              </h3>
              {!item.attempt_id && (
                <p className="text-sm text-muted-foreground">
                  {t({ zh: "未作答", en: "Unanswered" })}
                </p>
              )}
              {query?.isPending && (
                <p role="status">
                  {t({ zh: "正在加载反馈…", en: "Loading feedback…" })}
                </p>
              )}
              {query?.isError && (
                <Button
                  variant="outline"
                  className="min-h-11"
                  onClick={() => void query.refetch()}
                >
                  {t({
                    zh: "反馈加载失败，重试",
                    en: "Feedback failed to load. Retry",
                  })}
                </Button>
              )}
              {attempt && (
                <>
                  {attempt.item_text && (
                    <p className="whitespace-pre-wrap break-words text-sm">
                      {attempt.item_text}
                    </p>
                  )}
                  {attempt.status === "done" ? (
                    <>
                      <p className="text-sm">
                        {t({ zh: "参考分", en: "Reference score" })}{" "}
                        {attempt.overall ?? "–"}
                      </p>
                      {attempt.advice?.length ? (
                        <ul className="list-disc space-y-1 break-words pl-5 text-sm">
                          {attempt.advice.map((line, lineIndex) => (
                            <li key={`${lineIndex}:${line}`}>{line}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-sm text-muted-foreground">
                          {t({
                            zh: "该题暂无 AI 文字建议。",
                            en: "No AI text advice for this item.",
                          })}
                        </p>
                      )}
                      {attempt.item_type === "question" && (
                        <RubricBlock
                          rubric={attempt.rubric}
                          engine={attempt.engine}
                        />
                      )}
                    </>
                  ) : (
                    <p role="status" className="text-sm">
                      {t(
                        attempt.status === "failed"
                          ? {
                              zh: "本次评分失败，暂无 AI 反馈。",
                              en: "Scoring failed; no AI feedback is available.",
                            }
                          : {
                              zh: "评分中，反馈会自动更新。",
                              en: "Scoring; feedback will update automatically.",
                            },
                      )}
                    </p>
                  )}
                </>
              )}
            </section>
          )
        })}
      </DialogContent>
    </Dialog>
  )
}
