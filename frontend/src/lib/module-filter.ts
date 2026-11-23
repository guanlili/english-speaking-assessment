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
