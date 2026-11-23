import type { ModuleKey } from "@/hooks/useModules"

/**
 * 按本校已购模块过滤导航条目：共享底座（无 module 标注）始终保留；
 * 标注模块的条目仅在已购时出现。服务端闸门是最终裁决，前端过滤只减少无效直达。
 */
export function filterItemsByModule<T extends { module?: ModuleKey | null }>(
  entries: T[],
  hasModule: (key: ModuleKey) => boolean,
): T[] {
  return entries.filter((entry) => !entry.module || hasModule(entry.module))
}

/** 模块入口守卫状态：加载中 / 未购或不可用（拦截）/ 已购放行。 */
export type ModuleGuardState = "loading" | "denied" | "allowed"

/**
 * 模块入口守卫判定（保守口径，与服务端闸门一致；前端只减少无效直达）：
 * - 加载中：清单未回来前先给骨架，不闪拦截页；
 * - 请求失败或缺省未含该模块：按未购拦截；
 * - 清单明确含该模块：放行。
 */
export function moduleGuardState(
  query: { isPending: boolean; isError: boolean },
  hasModule: (key: ModuleKey) => boolean,
  key: ModuleKey,
): ModuleGuardState {
  if (query.isPending) return "loading"
  if (query.isError || !hasModule(key)) return "denied"
  return "allowed"
}
