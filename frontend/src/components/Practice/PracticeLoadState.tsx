import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useI18n } from "@/lib/i18n"

/**
 * 练习页加载态（展示组件）：骨架与正式布局同构
 * （标题 HUD / 进度条 / 主卡 / 侧栏），由页面套 StudentShell。
 */
export function PracticeSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true">
      <div className="space-y-2">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-4 w-64" />
      </div>
      <Skeleton className="h-1.5 w-full rounded-full" />
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_270px]">
        <div className="grid gap-5">
          <Skeleton className="h-96 w-full rounded-2xl" />
        </div>
        <div className="hidden gap-4 lg:grid">
          <Skeleton className="h-44 rounded-2xl" />
          <Skeleton className="h-20 rounded-2xl" />
        </div>
      </div>
    </div>
  )
}

/**
 * 练习加载失败兜底（展示组件）：「老师未配置篇目与复述句」给出可行动
 * 的提示，其余错误提示刷新重试。contentMissing 从错误的 body.detail
 * 派生（稳定标识，与后端约定一致）。
 */
export function PracticeLoadError({
  error,
  onRetry,
}: {
  error: unknown
  onRetry: () => void
}) {
  const { t } = useI18n()
  const detail = (error as { body?: { detail?: string } })?.body?.detail
  const contentMissing =
    detail === "No active passage" ||
    detail === "No repeat sentences configured"
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-muted-foreground">
      {contentMissing ? (
        <>
          {t({
            zh: "今天还没有可以练习的内容。",
            en: "No practice content is available today.",
          })}
          <span className="text-sm">
            {t({
              zh: "请联系老师在后台配置篇目和复述句，配好后回来刷新即可。",
              en: "Please ask your teacher to set up passages and repeat sentences; refresh here once they're ready.",
            })}
          </span>
        </>
      ) : (
        t({
          zh: "练习加载失败，请刷新重试。",
          en: "Practice failed to load — please refresh and retry.",
        })
      )}
      <Button variant="outline" onClick={onRetry}>
        {t({ zh: "重试", en: "Retry" })}
      </Button>
    </div>
  )
}
