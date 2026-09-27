/**
 * 学生身份本地存储：课堂码 + 显示名（PRD US-04：无正式账号，
 * 刷新后仍是同一个人，BDD B）。键按课堂码隔离。
 */

import type { StudentJoined } from "@/client"

export interface StoredStudent {
  id: string
  display_name: string
  suffix: string | null
  access_token: string
}

const keyFor = (code: string) => `esa:student:${code.toUpperCase()}`

export function saveStudent(code: string, student: StudentJoined): void {
  const stored: StoredStudent = {
    id: student.id,
    display_name: student.display_name,
    suffix: student.suffix ?? null,
    access_token: student.access_token,
  }
  localStorage.setItem(keyFor(code), JSON.stringify(stored))
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

export function studentToken(code: string): string | null {
  return loadStudent(code)?.access_token ?? null
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
 * API 错误是否为「学生身份已失效」（清库/课堂重建后的身份/课堂 404）。
 * 内容缺失类 404（无篇目、无复述句、会话不存在）不清身份——那是老师
 * 侧配置问题，清掉会把学生踢回加入页并创建新身份，数据就断了。
 */
export function isStudentNotFound(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("status" in error))
    return false
  const e = error as { status?: number; body?: { detail?: unknown } }
  if (e.status !== 404) return false
  const detail = typeof e.body?.detail === "string" ? e.body.detail : undefined
  // 无 detail 的 404 保持旧行为（视为身份失效）；有 detail 时只认身份类
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
