import { useQuery } from "@tanstack/react-query"

import { type ModuleStatus, ModulesService } from "@/client"
import { isLoggedIn, isOperatorLoggedIn } from "@/hooks/useAuth"

export type ModuleKey = "speaking" | "vocabulary"

export const modulesQueryKey = ["modulesMe"] as const

/**
 * 清单新鲜窗口：45s 内复用缓存，窗口外聚焦 / 标签重新可见时才重取。
 */
const MODULES_STALE_TIME_MS = 45 * 1000

/**
 * 当前学校用户已购（已生效）模块清单。
 *
 * 口径与服务端闸门一致：缺行/关闭/未到生效时间均不计入；平台运营身份不走
 * 本端点（运营没有「本校模块」概念）。导航与入口按本清单显隐，服务端仍是
 * 最终裁决——前端隐藏只是减少无效直达。
 *
 * `statuses` 是后端按状态机派生的逐模块快照（state/grant_type/days_left…），
 * 供校管后台到期提醒横幅使用；`modules` 仍是「可访问」清单，行为不变。
 *
 * 生效体验：清单 staleTime 45s，且 `refetchOnWindowFocus: true`——由 react-query
 * 内置 focusManager 监听窗口聚焦 / 可见性变化，**仅当缓存已超过 45s 才重取**，
 * 不在 45s 内来回切 tab 时打请求，也不另写全局 visibilitychange 轮询。模块
 * effective_at 到点后，≤45s 内或切回标签页时清单自动刷新，入口随之出现，
 * 无需整页刷新。
 */
export function useModules(enabled = true) {
  const query = useQuery<{ modules: string[]; statuses: ModuleStatus[] }>({
    queryKey: modulesQueryKey,
    queryFn: async () => {
      const res = await ModulesService.readModulesMe()
      return {
        modules: res.modules ?? [],
        statuses: res.statuses ?? [],
      }
    },
    enabled: enabled && isLoggedIn() && !isOperatorLoggedIn(),
    staleTime: MODULES_STALE_TIME_MS,
    refetchOnWindowFocus: true,
  })

  const modules = new Set(query.data?.modules ?? [])
  const statuses = query.data?.statuses ?? []
  const statusMap = new Map<string, ModuleStatus>(
    statuses.map((s) => [s.module_key, s]),
  )
  return {
    ...query,
    modules,
    statuses,
    statusMap,
    hasModule: (key: ModuleKey) => modules.has(key),
    statusOf: (key: ModuleKey) => statusMap.get(key),
  }
}
