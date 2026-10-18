import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { ClassesService, type FollowupEvidence } from "@/client"
import { AttemptFeedbackDialog } from "@/components/Teaching/AttemptFeedbackDialog"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"

export function FollowupOutcomesDialog({
  code,
  taskId,
  onClose,
}: {
  code: string
  taskId: string
  onClose: () => void
}) {
  const { t, lang } = useI18n()
  const [offset, setOffset] = useState(0)
  const [attemptId, setAttemptId] = useState<string | null>(null)
  const query = useQuery({
    queryKey: ["teacher", "followup-outcomes", code, taskId, offset],
    queryFn: () =>
      ClassesService.readFollowupOutcomes({ code, taskId, offset, limit: 10 }),
    refetchInterval: 10000,
  })
  const label = (row: FollowupEvidence | null) =>
    !row
      ? t({ zh: "暂无作答", en: "No answer" })
      : row.status === "done"
        ? t({
            zh: `参考分 ${row.overall ?? "—"} · ${row.engine}`,
            en: `Reference score ${row.overall ?? "—"} · ${row.engine}`,
          })
        : row.status === "failed"
          ? t({ zh: "评分失败", en: "Scoring failed" })
          : t({ zh: "评分中", en: "Scoring" })
  return (
    <>
      <Dialog
        open
        onOpenChange={(open) => {
          if (!open) onClose()
        }}
      >
        <DialogContent className="sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "补练效果追踪", en: "Follow-up practice outcomes" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "逐题对照布置前的最近一次原作答与补练最近一次作答。同引擎且均评分完成时显示参考分变化，不作为能力提升结论，也不是官方成绩。",
                en: "Compare the latest source answer before assignment with the latest follow-up answer per item. Score changes appear only for completed answers from the same engine; they are not evidence of ability gains or official results.",
              })}
            </DialogDescription>
          </DialogHeader>
          {query.isPending ? (
            <p role="status">
              {t({ zh: "正在加载补练效果…", en: "Loading outcomes…" })}
            </p>
          ) : query.isError ? (
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() => void query.refetch()}
            >
              {t({
                zh: "效果加载失败，重试",
                en: "Outcomes unavailable. Retry",
              })}
            </Button>
          ) : (
            <>
              <p className="break-words font-medium">{query.data.title}</p>
              <p className="text-sm text-muted-foreground">
                {query.data.source_title}
                {query.data.assigned_at &&
                  ` · ${formatDateTime(query.data.assigned_at, lang)}`}
              </p>
              {query.data.students.map((student) => (
                <article
                  key={student.student_id}
                  className="min-w-0 space-y-3 rounded-xl border p-4"
                >
                  <h3 className="break-words font-semibold">
                    {student.display_name} · {student.completed_items}/
                    {student.total_items}{" "}
                    {t({ zh: "题完成", en: "items completed" })}
                  </h3>
                  {student.items.map((item, index) => (
                    <section
                      key={item.item_id}
                      className="space-y-3 border-t pt-3"
                    >
                      <h4 className="break-words font-medium">
                        {index + 1}. {item.text}
                      </h4>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {(["original", "followup"] as const).map((kind) => (
                          <div
                            className="min-w-0 space-y-2 rounded-lg bg-muted/40 p-3"
                            key={kind}
                          >
                            <p className="text-sm font-medium">
                              {kind === "original"
                                ? t({
                                    zh: "原作答（布置前）",
                                    en: "Source answer (before assignment)",
                                  })
                                : t({
                                    zh: "补练作答（最近一次）",
                                    en: "Follow-up answer (latest)",
                                  })}
                            </p>
                            <p className="break-words text-sm">
                              {label(item[kind])}
                            </p>
                            {item[kind]?.teacher_feedback && (
                              <p className="whitespace-pre-wrap break-words text-sm">
                                {t({
                                  zh: "教师评价：",
                                  en: "Teacher feedback: ",
                                })}
                                {item[kind]?.teacher_feedback}
                              </p>
                            )}
                            {item[kind]?.teacher_focus && (
                              <p className="text-sm">
                                {t({
                                  zh: "教师重点关注",
                                  en: "Teacher focus area",
                                })}
                              </p>
                            )}
                            {item[kind] && (
                              <Button
                                variant="outline"
                                className="min-h-11"
                                onClick={() =>
                                  setAttemptId(item[kind]!.attempt_id)
                                }
                              >
                                {kind === "original"
                                  ? t({
                                      zh: "查看原作答",
                                      en: "View source answer",
                                    })
                                  : t({
                                      zh: "查看补练并点评",
                                      en: "Review follow-up and give feedback",
                                    })}
                              </Button>
                            )}
                          </div>
                        ))}
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {item.reference_change !== null
                          ? t({
                              zh: `同题参考分变化：${item.reference_change > 0 ? "+" : ""}${item.reference_change}`,
                              en: `Same-item reference score change: ${item.reference_change > 0 ? "+" : ""}${item.reference_change}`,
                            })
                          : t({
                              zh: "暂不计算参考分变化（作答缺失、未出分或引擎不同）。",
                              en: "Score change unavailable: missing answer, pending score or different engines.",
                            })}
                      </p>
                    </section>
                  ))}
                </article>
              ))}
              <nav
                className="flex flex-wrap items-center gap-3"
                aria-label={t({ zh: "补练效果分页", en: "Outcome pages" })}
              >
                <Button
                  variant="outline"
                  className="min-h-11"
                  disabled={offset === 0 || query.isFetching}
                  onClick={() => setOffset((value) => Math.max(0, value - 10))}
                >
                  {t({ zh: "上一页", en: "Previous" })}
                </Button>
                <span className="text-sm">
                  {t({
                    zh: `共 ${query.data.total_students} 人`,
                    en: `${query.data.total_students} students`,
                  })}
                </span>
                <Button
                  variant="outline"
                  className="min-h-11"
                  disabled={
                    offset + 10 >= query.data.total_students || query.isFetching
                  }
                  onClick={() => setOffset((value) => value + 10)}
                >
                  {t({ zh: "下一页", en: "Next" })}
                </Button>
              </nav>
            </>
          )}
        </DialogContent>
      </Dialog>
      {attemptId && (
        <AttemptFeedbackDialog
          attemptId={attemptId}
          open
          onClose={() => {
            setAttemptId(null)
            void query.refetch()
          }}
        />
      )}
    </>
  )
}
