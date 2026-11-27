import { useQuery } from "@tanstack/react-query"

import { ChangelogService } from "@/client"
import useAuth, { cachedRole } from "@/hooks/useAuth"

/** 侧栏红点的已读水位：存最近一次看过的最新条目日期（YYYY-MM-DD）。 */
export const CHANGELOG_SEEN_KEY = "esa:changelog-seen"

export const changelogQueryKey = ["changelog"] as const

/** 平台更新日志列表（教师/校级管理员/平台运营共用；侧栏红点与页面同键共享缓存）。 */
export function useChangelog() {
  const { user } = useAuth()
  // 优先用接口返回的 role（真值），兜底登录时缓存的 role。
  // 不能只认字面量白名单：一旦出现未覆盖的角色值（如 B3 改名后的
  // school_admin），enabled 恒为 false，查询永远停在 pending —— 页面就一直
  // 显示「加载中…」且不报错，比 403 更难查。
  const role = user?.role ?? cachedRole()
  return useQuery({
    queryKey: changelogQueryKey,
    queryFn: () => ChangelogService.readChangelog(),
    // 读=教职工（school_admin/teacher，含旧值 admin）与平台运营；
    // 仅排除学生——学生看这条是 403，不发请求。
    enabled: !!user && !!role && role !== "student",
    staleTime: 5 * 60 * 1000,
  })
}

/** 是否有未读更新：最新条目日期晚于已读水位（或从未看过且存在条目）。 */
export function useChangelogHasNew(): boolean {
  const { data } = useChangelog()
  if (!data?.length) return false
  const seen = localStorage.getItem(CHANGELOG_SEEN_KEY)
  return seen === null || data[0].day > seen
}

/** 进入更新页时刷新已读水位（没有条目时也落一个当天值，清掉红点）。 */
export function markChangelogSeen(latestDay: string | undefined) {
  localStorage.setItem(
    CHANGELOG_SEEN_KEY,
    latestDay ?? new Date().toISOString().slice(0, 10),
  )
}
