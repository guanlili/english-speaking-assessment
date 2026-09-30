import { useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"
import {
  clearStudent,
  isStudentNotFound,
  type StoredStudent,
} from "@/lib/classroom-student"

/**
 * 学生页身份守卫（5 个学生页共用的跳转逻辑，防多处复制漂移）：
 *
 * - 本地无学生身份（未加入/被清）→ 跳加入页 /j/$code
 * - 所传 query 报「学生/课堂不存在」（清库、课堂重建后的 404）
 *   → 清除本地身份再跳加入页，让学生重新进班
 *
 * 用法：useStudentGuard(code, student, todayQuery, pathQuery…)
 * 传 0..n 个 react-query 结果对象均可。
 */
export function useStudentGuard(
  code: string,
  student: StoredStudent | null,
  ...queries: Array<{ isError: boolean; error: unknown }>
) {
  const navigate = useNavigate()
  // queries 数组每次渲染都是新引用；用聚合键感知"是否有守卫型错误"变化
  const notFoundKey = queries
    .map((q) => (q.isError && isStudentNotFound(q.error) ? "1" : "0"))
    .join("")

  useEffect(() => {
    if (student === null) {
      void navigate({ to: "/j/$code", params: { code } })
      return
    }
    if (notFoundKey.includes("1")) {
      clearStudent(code)
      void navigate({ to: "/j/$code", params: { code } })
    }
    // biome-ignore lint/correctness/useExhaustiveDependencies: queries 每渲染新建，已由 notFoundKey 聚合；navigate 来自路由器保持稳定
  }, [student, code, notFoundKey, navigate])
}
