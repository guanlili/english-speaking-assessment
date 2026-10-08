import { Skeleton } from "@/components/ui/skeleton"

/**
 * 路由级默认 pending 骨架：autoCodeSplitting 下懒加载路由 chunk 时
 * TanStack Router 会挂起匹配，此组件作为全站统一的等待态。
 */
export default function RoutePending() {
  return (
    <div
      aria-busy="true"
      className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 p-4"
    >
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-72" />
      <Skeleton className="h-[420px] w-full rounded-2xl" />
    </div>
  )
}
