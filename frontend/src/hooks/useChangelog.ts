import { useQuery } from "@tanstack/react-query"

import { ChangelogService } from "@/client"
import useAuth from "@/hooks/useAuth"

/** 侧栏红点的已读水位：存最近一次看过的最新条目日期（YYYY-MM-DD）。 */
export const CHANGELOG_SEEN_KEY = "esa:changelog-seen"

export const changelogQueryKey = ["changelog"] as const

/** 平台更新日志列表（教师与管理员共用；侧栏红点与页面同键共享缓存）。 */
export function useChangelog() {
  const { user } = useAuth()
  return useQuery({
    queryKey: changelogQueryKey,
    queryFn: () => ChangelogService.readChangelog(),
    enabled: !!user,
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
