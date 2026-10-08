import { Send } from "lucide-react"
import type {
  AssignmentItemIn,
  ClassroomExercisePublic,
  InstructionPublic,
  PassageWithSentences,
  ScenarioOut,
  SentenceWithPassage,
} from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import { assignmentItemKey } from "@/lib/assignment-order"
import { useI18n } from "@/lib/i18n"
import { ITEM_TYPE_LABELS } from "@/lib/terms"

/**
 * 练习预览：学生将按此顺序作答；拆分文章展开为逐句清单。
 * 确认发布走 onPublish（幂等由页面 mutation 保证）。
 */
export function PreviewDialog({
  code,
  open,
  onOpenChange,
  planItems,
  selectedPassages,
  selectedSentences,
  selectedInstructions,
  scenarioQuestions,
  publishPending,
  changed,
  problemsCount,
  onPublish,
}: {
  code: string
  open: boolean
  onOpenChange: (open: boolean) => void
  planItems: AssignmentItemIn[]
  selectedPassages: PassageWithSentences[]
  selectedSentences: SentenceWithPassage[]
  selectedInstructions: InstructionPublic[]
  scenarioQuestions: ScenarioOut["questions"]
  publishPending: boolean
  changed: boolean
  problemsCount: number
  onPublish: () => void
}) {
  const { t } = useI18n()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {t({ zh: "练习预览", en: "Practice Preview" })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: `发布到课堂 ${code}。学生按以下顺序作答；已有作答的处理沿用当前课堂规则。`,
              en: `Will be published to classroom ${code}. Students answer in the order below; existing answers follow the classroom's current rules.`,
            })}
          </DialogDescription>
        </DialogHeader>
        <ol className="space-y-3">
          {planItems.map((item, index) => {
            const source =
              item.type === "passage"
                ? selectedPassages.find((p) => p.id === item.id)
                : item.type === "repeat"
                  ? selectedSentences.find((s) => s.id === item.id)
                  : item.type === "instruction"
                    ? selectedInstructions.find((i) => i.id === item.id)
                    : scenarioQuestions.find((q) => q.id === item.id)
            // 拆分文章：预览展示学生将逐句作答的句子清单（句序固定按原文）
            const splitSegments =
              item.type === "passage" &&
              source &&
              "reading_segments" in source &&
              source.reading_split
                ? (source.reading_segments ?? [])
                : []
            return (
              <li
                key={assignmentItemKey(item)}
                className="rounded-xl border p-4"
              >
                <h3 className="font-semibold">
                  {index + 1}.{" "}
                  {t(
                    ITEM_TYPE_LABELS[item.type] ?? {
                      zh: item.type,
                      en: item.type,
                    },
                  )}
                  {item.type === "passage" && source && "title" in source
                    ? ` · ${source.title}`
                    : ""}
                  {item.type === "instruction" &&
                  source &&
                  "title" in source &&
                  source.title
                    ? ` · ${source.title}`
                    : ""}
                  {item.type === "passage" && splitSegments.length > 0
                    ? t({
                        zh: ` · 逐句 ${splitSegments.length} 题`,
                        en: ` · ${splitSegments.length} sentence questions`,
                      })
                    : ""}
                </h3>
                {splitSegments.length > 0 ? (
                  <ol className="mt-2 space-y-1.5">
                    {splitSegments.map((segment, si) => (
                      <li
                        key={`${si}-${segment}`}
                        className="flex min-w-0 gap-2 text-sm leading-6"
                      >
                        <span className="shrink-0 text-xs leading-6 text-muted-foreground">
                          {si + 1}.
                        </span>
                        <span className="min-w-0 break-words [overflow-wrap:anywhere]">
                          {segment}
                        </span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
                    {source?.text}
                  </p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.type === "instruction"
                    ? t({
                        zh: `学生读完点「继续」进入下一题；模考中按 ${source?.suggested_seconds ?? 20} 秒倒计时，可提前继续`,
                        en: `Students tap Continue to move on; timed ${source?.suggested_seconds ?? 20}s in exams, skippable early`,
                      })
                    : splitSegments.length > 0
                      ? t({
                          zh: "学生将逐句朗读，每句单独录音评分",
                          en: "Students read aloud sentence by sentence, one recording each",
                        })
                      : t({
                          zh: `建议 ${source?.suggested_seconds ?? 0} 秒`,
                          en: `Suggested ${source?.suggested_seconds ?? 0}s`,
                        })}
                </p>
              </li>
            )
          })}
        </ol>
        <DialogFooter>
          <Button
            variant="outline"
            disabled={publishPending}
            onClick={() => onOpenChange(false)}
          >
            {t({ zh: "返回修改", en: "Back to Edit" })}
          </Button>
          <LoadingButton
            loading={publishPending}
            disabled={problemsCount > 0 || !changed}
            onClick={onPublish}
          >
            <Send className="size-4" />
            {changed
              ? t({
                  zh: "确认发布到课堂",
                  en: "Confirm Publish to Classroom",
                })
              : t({
                  zh: "与当前发布一致",
                  en: "Same as current publish",
                })}
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** 发布历史（课堂练习版本，含已归档）。 */
export function PublishHistory({
  exerciseHistory,
}: {
  exerciseHistory: ClassroomExercisePublic[]
}) {
  const { t } = useI18n()
  if (exerciseHistory.length === 0) return null
  return (
    <details className="rounded-2xl border bg-card px-5 py-4">
      <summary className="cursor-pointer text-sm font-semibold">
        {t({
          zh: `发布历史（${exerciseHistory.length} 个版本）`,
          en: `Publish History (${exerciseHistory.length} versions)`,
        })}
      </summary>
      <div className="mt-4 divide-y text-sm">
        {exerciseHistory.map((exercise) => (
          <div
            key={exercise.id}
            className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0"
          >
            <span>
              {t({
                zh: `v${exercise.version_no} · ${exercise.title} · ${exercise.item_count} 道题`,
                en: `v${exercise.version_no} · ${exercise.title} · ${exercise.item_count} items`,
              })}
            </span>
            <span className="text-xs text-muted-foreground">
              {exercise.status === "published"
                ? t({ zh: "当前发布", en: "Current publish" })
                : t({ zh: "已归档", en: "Archived" })}
              {exercise.published_at
                ? ` · ${new Date(exercise.published_at).toLocaleString()}`
                : ""}
            </span>
          </div>
        ))}
      </div>
    </details>
  )
}
