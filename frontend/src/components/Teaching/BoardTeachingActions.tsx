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
    <Card className="border-primary/20 bg-secondary/30">
      <CardContent className="flex flex-wrap items-center gap-3 py-4">
        <div className="mr-auto min-w-48">
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <ClipboardCheck className="size-4 text-primary" />{" "}
            {t({ zh: "教学动作", en: "Teaching Actions" })}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {attentionCount > 0
              ? t({
                  zh: `有 ${attentionCount} 位学生还没完成本轮。`,
                  en: `${attentionCount} student(s) haven't finished this round.`,
                })
              : t({
                  zh: "本轮已全部提交，可以进入下一次安排。",
                  en: "Everyone has submitted this round — ready for the next assignment.",
                })}
          </p>
        </div>
        {attentionCount > 0 && (
          <Button variant="outline" size="sm" onClick={onCopyReminder}>
            <MessageCircle /> {t({ zh: "复制提醒文案", en: "Copy Reminder" })}
          </Button>
        )}
        <Button size="sm" onClick={onAssignNext}>
          {t({ zh: "安排下一次练习", en: "Assign Next Practice" })}
        </Button>
      </CardContent>
    </Card>
  )
}
