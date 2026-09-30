/**
 * 表达收藏（升级表达）本地存储：按用户隔离。
 *
 * 共享设备场景 A→退出→B→A：收藏必须跟登录账号走，不能把 A 的收藏
 * 展示给 B，也不能把旧的无归属收藏自动分配给下一位登录者。
 *
 * - 登录学生：按 user_id（用户账号 ID）隔离，退出/换人后各自独立。
 * - 匿名学生（无 user_id）：按学生档案 id 隔离（同账号匿名与登录不混）。
 * 旧键 esa:saved-expressions（无归属）不再读取，避免串号。
 */

import { safeLocalStorageGet, safeLocalStorageSet } from "../utils.ts"
import type { StoredStudent } from "./classroom-student.ts"

/** 旧的无归属收藏键：停止使用（读它会串号）。 */
export const LEGACY_SAVED_EXPRESSIONS_KEY = "esa:saved-expressions"

export function savedExpressionsKey(student: StoredStudent): string {
  const owner = student.user_id ?? `anon:${student.id}`
  return `esa:saved-expressions:${owner}`
}

export function readSavedExpressions(student: StoredStudent): string[] {
  return safeLocalStorageGet<string[]>(savedExpressionsKey(student), [])
}

export function saveSavedExpressions(
  student: StoredStudent,
  expressions: string[],
): void {
  safeLocalStorageSet(savedExpressionsKey(student), expressions)
}
