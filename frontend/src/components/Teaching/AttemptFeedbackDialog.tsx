import { useQuery } from "@tanstack/react-query"
import { Loader2, TriangleAlert } from "lucide-react"
import { AttemptsService } from "@/client"
import AttemptAudio from "@/components/Practice/AttemptAudio"
import { ENGINE_LABELS, RubricBlock } from "@/components/Practice/FeedbackCard"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Separator } from "@/components/ui/separator"
import { useI18n } from "@/lib/i18n"
import { ITEM_TYPE_LABELS } from "@/lib/terms"

/**
 * 教师端逐题详细反馈弹窗：拉 readAttempt 展示题干（提交时快照）、
 * 转写、三维参考分、建议与音频回放。名单表与发布历史结果页共用。
 * 权限由后端 /attempts/{id} 校验（本人学生或授权教师）。
 */
export function AttemptFeedbackDialog({
  attemptId,
  open,
  onClose,
}: {
  attemptId: string | null
  open: boolean
  onClose: () => void
}) {
  const { t } = useI18n()
  const attemptQuery = useQuery({
    queryKey: ["attempt-detail", attemptId],
    queryFn: () => AttemptsService.readAttempt({ attemptId: attemptId! }),
    enabled: open && attemptId !== null,
    retry: 1,
  })
  const attempt = attemptQuery.data

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t({ zh: "学生作答详情", en: "Student attempt details" })}
          </DialogTitle>
          <DialogDescription>
            {attempt
              ? t(
                  ITEM_TYPE_LABELS[attempt.item_type] ?? {
                    zh: attempt.item_type,
                    en: attempt.item_type,
                  },
                )
              : t({
                  zh: "同一条作答的题干、转写与参考反馈",
                  en: "Item prompt, transcript and reference feedback of one attempt",
                })}
          </DialogDescription>
        </DialogHeader>

        {attemptQuery.isPending && (
          <p
            role="status"
            className="flex items-center gap-2 text-sm text-muted-foreground"
          >
            <Loader2 className="size-4 animate-spin" />
            {t({ zh: "正在加载作答…", en: "Loading attempt…" })}
          </p>
        )}
        {attemptQuery.isError && (
          <p role="alert" className="text-sm text-muted-foreground">
            {t({
              zh: "作答加载失败，请关闭后重试。",
              en: "Failed to load the attempt — close and retry.",
            })}
          </p>
        )}

        {attempt &&
          (attempt.status === "queued" || attempt.status === "scoring") && (
            <p
              role="status"
              className="flex items-center gap-2 text-sm text-muted-foreground"
            >
              <Loader2 className="size-4 animate-spin" />
              {t({
                zh: "录音正在评分，稍后再打开可见完整反馈。",
                en: "The recording is being scored — reopen later for full feedback.",
              })}
            </p>
          )}
        {attempt && attempt.status === "failed" && (
          <p className="flex items-center gap-2 text-sm text-destructive">
            <TriangleAlert className="size-4" />
            {t({
              zh: "这次作答未评出分数（评分失败）。",
              en: "No score for this attempt (scoring failed).",
            })}
          </p>
        )}

        {attempt && (
          <div className="space-y-3">
            {/* 题干（提交时快照）：题库此后被编辑/删除不影响此处展示 */}
            {(attempt.item_title || attempt.item_text) && (
              <div>
                {attempt.item_title && (
                  <p className="text-xs font-semibold text-muted-foreground">
                    {attempt.item_title}
                  </p>
                )}
                <p className="text-sm leading-relaxed font-medium whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                  {attempt.item_text}
                </p>
              </div>
            )}
            <Separator />
            <div>
              <p className="mb-1 text-xs text-muted-foreground">
                {t({
                  zh: "学生说了什么（转写）",
                  en: "What the student said (transcript)",
                })}
              </p>
              <p className="rounded-lg bg-background p-3 text-sm leading-relaxed">
                {attempt.transcript ||
                  t({ zh: "（无转写）", en: "(no transcript)" })}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-4 text-sm">
              <span className="text-2xl font-bold tabular-nums">
                {t({ zh: "参考分", en: "Score" })} {attempt.overall ?? "–"}
              </span>
              {attempt.item_type !== "question" && (
                <span className="text-muted-foreground">
                  {t({ zh: "完整度", en: "Completeness" })}{" "}
                  {attempt.completeness ?? "–"} ·{" "}
                  {t({ zh: "流利度", en: "Fluency" })} {attempt.fluency ?? "–"}
                </span>
              )}
              <Badge variant="secondary">
                {t(
                  ENGINE_LABELS[attempt.engine] ?? {
                    zh: attempt.engine,
                    en: attempt.engine,
                  },
                )}
              </Badge>
            </div>
            {attempt.advice && attempt.advice.length > 0 && (
              <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {attempt.advice.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
            {attempt.item_type === "question" && (
              <RubricBlock rubric={attempt.rubric} engine={attempt.engine} />
            )}
            <AttemptAudio
              attemptId={attempt.id}
              preload="metadata"
              className="w-full"
            />
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "参考反馈，不是考试成绩；转写可能有误，仅凭文本不能判断发音与语调。",
                en: "Reference feedback, not exam results; transcripts may err and text alone cannot judge pronunciation or intonation.",
              })}
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
