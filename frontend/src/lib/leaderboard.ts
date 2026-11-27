/**
 * 班内词汇学习榜纯函数（无 JSX，node --test 可直接测）。
 *
 * 口径对齐后端 `app/services/vocabulary_leaderboard.py`：
 * - 学生视角不可见（整班关闭 / 仅教师可见）返回 403 `leaderboard_unavailable`；
 * - 未参加学生 200 空榜，`participant_count` 永远为 null，看不到人数；
 * - 匿名时条目只带 `alias_no`，关闭匿名才给 `display_name`（可能带 `suffix`）；
 * - 周界按 PRACTICE_TZ 自然周；前端只回传后端返回过的周一，不自行用浏览器时区推断。
 */
import type { VocabularyLeaderboardEntry } from "@/client/types.gen"
import { ApiError } from "./api-error.ts"

/** 学生视角不可见的稳定标识（后端 detail，前端按文案分流，不得改措辞） */
export const LEADERBOARD_UNAVAILABLE_DETAIL = "leaderboard_unavailable"

/** 是否为「学生不可见」的 403（整班关闭或仅教师可见）；其他错误不在此列。 */
export function isLeaderboardUnavailable(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 403 &&
    error.message === LEADERBOARD_UNAVAILABLE_DETAIL
  )
}

/** 学生视角是否展示榜卡：200 且整班开启且对学生可见。 */
export function studentBoardVisible(view: {
  settings: { enabled: boolean; audience: string }
}): boolean {
  return view.settings.enabled && view.settings.audience === "students"
}

/** 参与人数是否对当前视角可见：仅教师视角且后端回传了计数。 */
export function participantCountVisible(
  participantCount: number | null | undefined,
): boolean {
  return participantCount != null
}

/** 两位编号：7 → "07"；负数 / 非整数兜底为 0。 */
export function padAliasNo(aliasNo: number): string {
  const safe = Number.isFinite(aliasNo) ? Math.max(0, Math.round(aliasNo)) : 0
  return String(safe).padStart(2, "0")
}

export type ResolvedEntryName =
  | { kind: "anonymous"; aliasNo: number }
  | { kind: "name"; name: string; suffix: string | null }

/**
 * 条目展示名：匿名（或后端未回传姓名）时只给编号；否则给姓名，
 * `suffix`（如同班同名后缀）由展示层小字消歧。
 */
export function resolveEntryName(
  entry: VocabularyLeaderboardEntry,
  anonymous: boolean,
): ResolvedEntryName {
  if (anonymous || !entry.display_name) {
    return { kind: "anonymous", aliasNo: entry.alias_no }
  }
  return {
    kind: "name",
    name: entry.display_name,
    suffix: entry.suffix ?? null,
  }
}

/** 周日期加减 7 天（ISO `YYYY-MM-DD`，UTC 解析，避免浏览器时区漂移）。 */
function shiftWeek(weekStart: string, weeks: number): string {
  const date = new Date(`${weekStart}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + weeks * 7)
  return date.toISOString().slice(0, 10)
}

/** 上一个自然周的周一（ISO `YYYY-MM-DD`）。 */
export function previousWeekStart(weekStart: string): string {
  return shiftWeek(weekStart, -1)
}

/** 下一个自然周的周一（ISO `YYYY-MM-DD`）；上界仍由调用方按 boundary 锁定。 */
export function nextWeekStart(weekStart: string): string {
  return shiftWeek(weekStart, 1)
}

/** 能否切到下一周：不超过首次响应拿到的本周（上界由后端 week_start 锁定）。 */
export function canGoNextWeek(
  currentWeekStart: string,
  boundaryWeekStart: string | null,
): boolean {
  return boundaryWeekStart !== null && currentWeekStart !== boundaryWeekStart
}
