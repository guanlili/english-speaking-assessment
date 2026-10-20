import { useQuery, useQueryClient } from "@tanstack/react-query"
import { type AttemptPublic, AttemptsService, type BoardItem } from "@/client"
import { ENGINE_LABELS, RubricBlock } from "@/components/Practice/FeedbackCard"
import { SkippedSpans } from "@/components/Practice/SkippedSpans"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"
import { pollWhileVisible } from "@/lib/poll"
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
  const queryClient = useQueryClient()
  const questions = items.filter((item) => item.type !== "instruction")
  const attemptIds = [
    ...new Set(
      questions.flatMap((item) => (item.attempt_id ? [item.attempt_id] : [])),
    ),
  ].sort()
  const query = useQuery<AttemptPublic[]>({
    // Flat IDs let feedback edits invalidate both batch and single-attempt queries.
    queryKey: ["attempt-detail", "batch", ...attemptIds],
    queryFn: async ({ signal }) => {
      const attempts = await AttemptsService.readAttemptsBatch({
        requestBody: { attempt_ids: attemptIds },
      })
      // A cancelled batch must not repopulate caches after logout.
      if (!signal.aborted) {
        for (const attempt of attempts) {
          queryClient.setQueryData(["attempt-detail", attempt.id], attempt)
        }
      }
      return attempts
    },
    enabled: open && attemptIds.length > 0,
    retry: 1,
    refetchInterval: pollWhileVisible((query) =>
      query.state.data?.some(
        (attempt) =>
          attempt.status === "queued" ||
          attempt.status === "scoring" ||
          attempt.rubric?.status === "pending",
      )
        ? 3000
        : false,
    ),
  })
  const byId = new Map(query.data?.map((attempt) => [attempt.id, attempt]))
  const submitted = questions.flatMap((item) => {
    const attempt = item.attempt_id ? byId.get(item.attempt_id) : undefined
    return attempt ? [attempt] : []
  })
  const scores = submitted.flatMap((attempt) =>
    attempt.status === "done" && attempt.overall != null
      ? [attempt.overall]
      : [],
  )
  const doneCount = submitted.filter(
    (attempt) => attempt.status === "done",
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
              zh: "本条记录各题已保存的反馈；参考分为已评分题目均值，并非独立生成的整轮 AI 总评。",
              en: "Saved feedback for each item in this record; the reference score averages scored items. This is not a separately generated overall AI review.",
            })}
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm">
          {t({
            zh: `已评分 ${doneCount}/${questions.length} 题 · 参考分 ${average}`,
            en: `${doneCount}/${questions.length} items scored · reference score ${average}`,
          })}
        </p>
        {attemptIds.length === 0 && (
          <p>
            {t({
              zh: "这条记录暂无作答反馈。",
              en: "No answer feedback for this record yet.",
            })}
          </p>
        )}
        {attemptIds.length > 0 && query.isPending && (
          <p role="status">
            {t({ zh: "正在加载反馈…", en: "Loading feedback…" })}
          </p>
        )}
        {attemptIds.length > 0 && query.isError && (
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
        {questions.map((item, index) => {
          const attempt = item.attempt_id
            ? byId.get(item.attempt_id)
            : undefined
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
              {attempt && (
                <>
                  {attempt.item_text && (
                    <p className="whitespace-pre-wrap break-words text-sm">
                      {attempt.item_text}
                    </p>
                  )}
                  {attempt.status === "done" ? (
                    <>
                      <p className="text-xs text-muted-foreground">
                        {t(
                          ENGINE_LABELS[attempt.engine] ?? {
                            zh: `转写来源 · ${attempt.engine}`,
                            en: `Transcript source · ${attempt.engine}`,
                          },
                        )}
                      </p>
                      <p className="text-sm font-medium">
                        {t({
                          zh: "规则评分与建议",
                          en: "Rule-based score and advice",
                        })}
                      </p>
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
                            zh: "该题暂无规则建议。",
                            en: "No rule-based advice for this item.",
                          })}
                        </p>
                      )}
                      <SkippedSpans
                        reference={attempt.item_text}
                        transcript={attempt.transcript}
                        itemType={attempt.item_type}
                      />
                      {attempt.item_type === "question" && (
                        <div className="space-y-2">
                          <p className="text-sm font-medium">
                            {t({
                              zh: "模型详细评价",
                              en: "Model-generated detailed review",
                            })}
                          </p>
                          {attempt.rubric || attempt.engine === "ark" ? (
                            <RubricBlock
                              rubric={attempt.rubric}
                              engine={attempt.engine}
                            />
                          ) : (
                            <p className="text-sm text-muted-foreground">
                              {t({
                                zh: "暂无模型评价。",
                                en: "No model review is available.",
                              })}
                            </p>
                          )}
                        </div>
                      )}
                    </>
                  ) : (
                    <p role="status" className="text-sm">
                      {t(
                        attempt.status === "failed"
                          ? {
                              zh: "本次评分失败，暂无反馈。",
                              en: "Scoring failed; no feedback is available.",
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
