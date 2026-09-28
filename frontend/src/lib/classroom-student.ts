/**
 * 学生课堂档案本地记录：登录态（JWT，见 useAuth）即身份；这里只记
 * 「该学生加入了哪些课堂」（入班响应），供刷新后续练与登录后跳转。
 * 键按课堂码隔离：esa:student:{CODE}。
 */

import type { StudentPublic } from "@/client"

export interface StoredStudent {
  id: string
  display_name: string
  suffix: string | null
  user_id: string | null
}

const keyFor = (code: string) => `esa:student:${code.toUpperCase()}`
const LAST_CODE_KEY = "esa:student:last-code"

export function saveStudent(code: string, student: StudentPublic): void {
  const stored: StoredStudent = {
    id: student.id,
    display_name: student.display_name,
    suffix: student.suffix ?? null,
    user_id: student.user_id ?? null,
  }
  localStorage.setItem(keyFor(code), JSON.stringify(stored))
  localStorage.setItem(LAST_CODE_KEY, code.toUpperCase())
}

export function loadStudent(code: string): StoredStudent | null {
  const raw = localStorage.getItem(keyFor(code))
  if (!raw) return null
  try {
    return JSON.parse(raw) as StoredStudent
  } catch {
    return null
  }
}

export function lastJoinedCode(): string | null {
  return localStorage.getItem(LAST_CODE_KEY)
}

export function clearStudent(code: string): void {
  localStorage.removeItem(keyFor(code))
}

export function displayName(student: StoredStudent): string {
  return student.suffix
    ? `${student.display_name}·${student.suffix}`
    : student.display_name
}

/**
 * API 错误是否为「学生课堂档案已失效」（被移出课堂/课堂重建的 404）。
 * 内容缺失类 404（无篇目、无复述句、会话不存在）不清记录——那是老师
 * 侧配置问题，清掉会把学生踢回加入页，数据就断了。
 */
export function isStudentNotFound(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("status" in error))
    return false
  const e = error as { status?: number; body?: { detail?: unknown } }
  if (e.status !== 404) return false
  const detail = typeof e.body?.detail === "string" ? e.body.detail : undefined
  if (detail === undefined) return true
  return detail === "Student not found" || detail === "Classroom not found"
}

export const WEEK_GOAL_KEY = "esa:week-goal"
export const DEFAULT_WEEK_GOAL = 5

export function readWeekGoal(): number {
  const v = Number(localStorage.getItem(WEEK_GOAL_KEY))
  return v === 3 || v === 5 || v === 7 ? v : DEFAULT_WEEK_GOAL
}

export function writeWeekGoal(goal: number): void {
  localStorage.setItem(WEEK_GOAL_KEY, String(goal))
}
