import { Repeat } from "lucide-react"
import type { PlanAttempt, PlanItem } from "@/client"
import AttemptAudio from "@/components/Practice/AttemptAudio"
import { AttemptComparison } from "@/components/Practice/AttemptComparison"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"
import { ITEM_TYPE_LABELS } from "@/lib/terms"

export function RoundReplayDialog({
  replay,
  isExam,
  onClose,
  onPracticeAgain,
}: {
  replay: { item: PlanItem; attempt: PlanAttempt } | null
  isExam: boolean
  onClose: () => void
  onPracticeAgain: (itemId: string) => void
}) {
  const { t } = useI18n()
  return (
    <Dialog open={replay !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {replay && (
              <>
                {t(
                  ITEM_TYPE_LABELS[replay.item.type] ?? {
                    zh: replay.item.type,
                    en: replay.item.type,
                  },
                )}{" "}
                · {t({ zh: "回看这次表达", en: "Review this attempt" })}
              </>
            )}
          </DialogTitle>
          <DialogDescription>{replay?.item.text}</DialogDescription>
        </DialogHeader>
        {replay && (
          <div className="space-y-3">
            <div>
              <p className="mb-1 text-xs text-muted-foreground">
                {t({
                  zh: "你说了什么（转写）",
                  en: "What you said (transcript)",
                })}
              </p>
              <p className="rounded-lg bg-background p-3 text-sm leading-relaxed">
                {replay.attempt.transcript ||
                  t({ zh: "（无转写）", en: "(no transcript)" })}
              </p>
            </div>
            <div className="flex items-center gap-3 text-sm">
              <span className="text-2xl font-bold tabular-nums">
                {replay.attempt.overall ?? "–"}
              </span>
              <span className="text-muted-foreground">
                {t({ zh: "参考分", en: "Reference Score" })}
              </span>
            </div>
            {!isExam && replay.attempt.attempt_id && (
              <AttemptComparison attemptId={replay.attempt.attempt_id} />
            )}
            {replay.attempt.attempt_id && (
              <AttemptAudio
                attemptId={replay.attempt.attempt_id}
                preload="metadata"
                className="w-full"
              />
            )}
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "听一听自己刚才的声音，找出下一句想说得更好的地方。",
                en: "Listen to your own voice and find the next sentence you'd like to say better.",
              })}
            </p>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t({ zh: "关闭", en: "Close" })}
          </Button>
          {!isExam && (
            <Button onClick={() => replay && onPracticeAgain(replay.item.id)}>
              <Repeat />
              {t({ zh: "再练这一题", en: "Practice this item again" })}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
