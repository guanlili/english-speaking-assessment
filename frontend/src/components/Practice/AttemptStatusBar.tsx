import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

/**
 * 08A 状态接线（展示组件）：rubric 评定中不是假死的可见指示 +
 * 轮询停止（403/404）后的只读重试入口——绝不重传音频、不新增幂等键。
 */
export function AttemptStatusBar({
  rubricPending,
  pollErrorStatus,
  onRefetch,
}: {
  rubricPending: boolean
  /** 轮询失败状态码；仅 403/404（停轮类）展示重试条 */
  pollErrorStatus: number | null
  onRefetch: () => void
}) {
  const { t } = useI18n()
  return (
    <>
      {rubricPending && (
        <div
          role="status"
          className="flex items-center gap-2 rounded-xl border bg-muted/30 px-4 py-3 text-sm text-muted-foreground"
        >
          <span className="size-2 animate-pulse rounded-full bg-primary" />
          {t({
            zh: "基础反馈已就绪，模拟分评定中…",
            en: "Feedback is ready. Mock score is being graded…",
          })}
        </div>
      )}
      {(pollErrorStatus === 403 || pollErrorStatus === 404) && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm"
        >
          <span>
            {t({
              zh: "评分查询失败（无权限或作答不存在）",
              en: "Cannot fetch your score (no access or attempt missing)",
            })}
          </span>
          <Button variant="outline" className="h-11" onClick={onRefetch}>
            {t({ zh: "重新查询", en: "Retry fetch" })}
          </Button>
        </div>
      )}
    </>
  )
}

export default AttemptStatusBar
