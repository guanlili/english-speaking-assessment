/**
 * 学生身份本地存储：课堂码 + 显示名（PRD US-04：无正式账号，
 * 刷新后仍是同一个人，BDD B）。键按课堂码隔离。
 */

import type { StudentPublic } from "@/client"

export interface StoredStudent {
  id: string
  display_name: string
  suffix: string | null
}

const keyFor = (code: string) => `esa:student:${code.toUpperCase()}`

export function saveStudent(code: string, student: StudentPublic): void {
  const stored: StoredStudent = {
    id: student.id,
    display_name: student.display_name,
    suffix: student.suffix ?? null,
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

export function clearStudent(code: string): void {
  localStorage.removeItem(keyFor(code))
}

export function displayName(student: StoredStudent): string {
  return student.suffix
    ? `${student.display_name}·${student.suffix}`
    : student.display_name
}
