import type { PkMatchItem, PkMatchView, PkPlayerSummary } from "@/client"

/**
 * 课堂 PK 前端纯函数：状态机派生、SSE/轮询降级判定、倒计时兜底与结算口径。
 *
 * 边界（设计稿 docs/vocabulary-pk-farm-design-20261122.md §1.2/§3）：
 * - SSE 断流/建连失败自动降级 1.5 秒轮询；轮询与 SSE 读同一套快照接口。
 * - 倒计时只做展示，服务端时钟为准；剩余秒数由后端快照下发，这里只兜底截断。
 * - 胜负口径：总分高者胜，同分比总用时；平局由后端标记 drew。
 */

export type PkPhase = "idle" | "waiting" | "match" | "finished" | "closed"

export interface PkLobbyLike {
  status?: string | null
  my_status?: string | null
  my_match_id?: string | null
}

/** 由大厅 + 对局快照派生当前页面阶段（纯派生，不触达接口）。 */
export function pkPhase(
  lobby: PkLobbyLike,
  match: PkMatchView | null,
): PkPhase {
  if (match?.status === "finished") return "finished"
  if (match && match.status === "active") return "match"
  if (lobby.status === "closed") return "closed"
  if (lobby.my_status === "waiting") return "waiting"
  if (lobby.my_match_id) return "match"
  return "idle"
}

/** 本人下一道未答题下标；全部答完返回题数（与后端视图口径一致）。 */
export function pkNextItemIndex(items: PkMatchItem[] | undefined): number {
  const list = items ?? []
  for (const item of list) {
    if (!item.answered) return item.item_index
  }
  return list.length
}

/** 剩余秒数兜底：null/负值截断为 0，取整。 */
export function pkRemainingSeconds(remaining?: number | null): number {
  if (remaining === null || remaining === undefined) return 0
  return Math.max(0, Math.round(remaining))
}

/**
 * SSE 降级判定：未建连，或距上一事件超过 `fallbackAfterMs` 即切轮询。
 * 多 worker 部署下以轮询为准（设计稿 §1.2），这里只给前端切换信号。
 */
export function pkShouldPolling(options: {
  sseOpen: boolean
  lastEventAt: number | null
  now: number
  fallbackAfterMs?: number
}): boolean {
  const { sseOpen, lastEventAt, now, fallbackAfterMs = 1500 } = options
  if (!sseOpen) return true
  if (lastEventAt === null) return true
  return now - lastEventAt > fallbackAfterMs
}

export type PkOutcome = "win" | "lose" | "drew" | "none"

/** 结算结果对本人的观感：胜 / 负 / 平 / 未结算。 */
export function pkOutcome(
  result: PkMatchView["result"],
  myStudentId?: string | null,
): PkOutcome {
  if (result?.status !== "finished") return "none"
  if (result.drew) return "drew"
  if (!result.winner_student_id) return "drew"
  return result.winner_student_id === myStudentId ? "win" : "lose"
}

/**
 * 作答幂等键：同局同玩家同题同次尝试稳定唯一，断网重传不二次计分。
 * 玩家维度取学生 ID 前 8 位（去横线）；服务端唯一约束/重放查询按 player_id
 * 兜底，前缀仅用于把两名玩家的键区分开，整体长度控制在 64 以内。
 */
export function pkAnswerKey(
  matchId: string,
  studentId: string | null | undefined,
  itemIndex: number,
  attempt: number,
): string {
  const player = (studentId ?? "").replace(/-/g, "").slice(0, 8) || "anon"
  return `${matchId}:${player}:${itemIndex}:${attempt}`
}

/**
 * 解析 SSE 文本缓冲：按空行切出完整事件块，保留未完成尾部待下次拼接。
 * 返回的事件块保留 `event:` / `data:` 原始行，交给上层取 data JSON。
 */
export function parseSseBuffer(buffer: string): {
  events: string[]
  rest: string
} {
  const normalized = buffer.replace(/\r\n/g, "\n")
  const chunks = normalized.split("\n\n")
  const rest = (chunks.pop() ?? "").replace(/^\n+/, "")
  return { events: chunks.filter((chunk) => chunk.trim() !== ""), rest }
}

/** 进行中对局分组：教师端大厅快照按 match_id 聚合 active 玩家，保持返回顺序。 */
export interface PkActiveMatch {
  matchId: string
  players: PkPlayerSummary[]
}

/** 等待配对中的玩家（status = waiting），保持快照顺序。 */
export function pkWaitingPlayers(
  players: PkPlayerSummary[] | undefined,
): PkPlayerSummary[] {
  return (players ?? []).filter((player) => player.status === "waiting")
}

/** 历史对局状态归类：finished 已结束 / abandoned 已放弃 / 其他未知状态。 */
export type PkHistoryStatusKey = "finished" | "abandoned" | "other"

export function pkHistoryStatusKey(status?: string | null): PkHistoryStatusKey {
  if (status === "finished") return "finished"
  if (status === "abandoned") return "abandoned"
  return "other"
}

/** 历史玩家结果归类：win 胜 / lose 负 / draw 平（空值按平局兜底）。 */
export type PkHistoryResultKey = "win" | "lose" | "draw"

export function pkHistoryResultKey(result?: string | null): PkHistoryResultKey {
  if (result === "win") return "win"
  if (result === "lose") return "lose"
  return "draw"
}

/** 胜者展示名：空串/无胜者（平局、放弃）返回 null，不折算成占位文案。 */
export function pkHistoryWinnerName(match: {
  winner_display_name?: string | null
}): string | null {
  const name = match.winner_display_name?.trim()
  return name ? name : null
}

/** 历史对局展示时间：优先结束时间，其次开始时间；都为空返回 null。 */
export function pkHistoryTime(match: {
  finished_at?: string | null
  started_at?: string | null
}): string | null {
  return match.finished_at ?? match.started_at ?? null
}

/** 进行中对局：active 且带 match_id 的玩家按对局分组；无对局返回空数组。 */
export function pkActiveMatches(
  players: PkPlayerSummary[] | undefined,
): PkActiveMatch[] {
  const groups = new Map<string, PkPlayerSummary[]>()
  for (const player of players ?? []) {
    if (player.status !== "active" || !player.match_id) continue
    const list = groups.get(player.match_id)
    if (list) list.push(player)
    else groups.set(player.match_id, [player])
  }
  return [...groups.entries()].map(([matchId, list]) => ({
    matchId,
    players: list,
  }))
}
