import { ClipboardCheck, MessageCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"

/**
 * 教学动作操作条（展示组件）：值得关注人数提示 +
 * 复制提醒文案 / 安排下一次练习两个动作，回调交由页面接线。
 */
export function BoardTeachingActions({
  attentionCount,
  onCopyReminder,
  onAssignNext,
}: {
  attentionCount: number
  onCopyReminder: () => void
  onAssignNext: () => void
}) {
  const { t } = useI18n()
  return (
    <Card className="border-primary/15 bg-secondary/40 py-0 shadow-none">
      <CardContent className="flex flex-wrap items-center gap-3 py-4">
        <div className="mr-auto min-w-0 flex-1 basis-48">
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <ClipboardCheck className="size-4 text-primary" />{" "}
            {t({ zh: "教学动作", en: "Teaching Actions" })}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {attentionCount > 0
              ? t({
                  zh: `有 ${attentionCount} 位学生需要关注。`,
                  en: `${attentionCount} student(s) need attention.`,
                })
              : t({
                  zh: "查看本轮反馈，或准备下一次课堂练习。",
                  en: "Review this round or prepare the next classroom practice.",
                })}
          </p>
        </div>
        {attentionCount > 0 && (
          <Button
            variant="outline"
            size="sm"
            className="min-h-11"
            onClick={onCopyReminder}
          >
            <MessageCircle /> {t({ zh: "复制提醒文案", en: "Copy Reminder" })}
          </Button>
        )}
        <Button size="sm" className="min-h-11" onClick={onAssignNext}>
          {t({ zh: "安排下一次练习", en: "Assign Next Practice" })}
        </Button>
      </CardContent>
    </Card>
  )
}
