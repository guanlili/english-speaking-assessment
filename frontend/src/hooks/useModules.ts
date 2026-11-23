import { useQuery } from "@tanstack/react-query"

import { ModulesService } from "@/client"
import { isLoggedIn, isOperatorLoggedIn } from "@/hooks/useAuth"

export type ModuleKey = "speaking" | "vocabulary"

export const modulesQueryKey = ["modulesMe"] as const

/**
 * 当前学校用户已购（已生效）模块清单。
 *
 * 口径与服务端闸门一致：缺行/关闭/未到生效时间均不计入；平台运营身份不走
 * 本端点（运营没有「本校模块」概念）。导航与入口按本清单显隐，服务端仍是
 * 最终裁决——前端隐藏只是减少无效直达。
 */
export function useModules(enabled = true) {
  const query = useQuery<{ modules: string[] }>({
    queryKey: modulesQueryKey,
    queryFn: async () => {
      const res = await ModulesService.readModulesMe()
      return { modules: res.modules ?? [] }
    },
    enabled: enabled && isLoggedIn() && !isOperatorLoggedIn(),
    staleTime: 5 * 60 * 1000,
  })

  const modules = new Set(query.data?.modules ?? [])
  return {
    ...query,
    modules,
    hasModule: (key: ModuleKey) => modules.has(key),
  }
}
