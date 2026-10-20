import type { Query } from "@tanstack/react-query"

/**
 * 页面不可见时暂停轮询的 refetchInterval 工厂。
 *
 * TanStack Query 的 refetchInterval 支持回调返回 `false` 停止轮询：
 * tab 隐藏/切走时停止，回到页面立即恢复；可见时行为与传入的
 * 固定间隔或回调完全一致。document 不存在（SSR/单测）时按可见处理。
 */
export function pollWhileVisible<
  TData,
  TError,
  TQueryKey extends readonly unknown[],
>(
  interval:
    | number
    | ((query: Query<TData, TError, TData, TQueryKey>) => number | false),
): (
  query: Query<TData, TError, TData, TQueryKey>,
) => number | false | undefined {
  return (query) => {
    if (typeof document !== "undefined" && document.hidden) return false
    return typeof interval === "function" ? interval(query) : interval
  }
}
