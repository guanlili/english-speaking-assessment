import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import { type UserPublic, UsersService } from "@/client"

/**
 * /admin 的布局路由：用户管理在 index，内容管理在 /admin/passages 等子路由。
 *
 * B3 身份拆分后的准入：
 * - 平台运营（esa:role=operator）：平台页（大盘/单元/用户/五级词库/句型/课堂管理）
 * - 教师：内容三页（三种题型的出题与管理）
 * - 校级管理员：教师三页 + 校内词库管理
 */
const TEACHER_ALLOWED = [
  "/admin/passages",
  "/admin/scenarios",
  "/admin/questions",
]

/** 校级管理员在教师三页之外加校内词库管理 */
const SCHOOL_ADMIN_ALLOWED = [...TEACHER_ALLOWED, "/admin/vocabbooks"]

/** 平台运营专属页（后端 PlatformOperatorDep） */
const OPERATOR_ALLOWED = [
  "/admin/dashboard",
  "/admin/units",
  "/admin/vocablevels",
  "/admin/sentenceframes",
  "/admin/classrooms",
]

let cachedUser: UserPublic | null = null
let cachedTokenFingerprint = ""
let cachedAt = 0
const CACHE_TTL = 5 * 60 * 1000

function tokenFingerprint(token: string): string {
  return token.slice(-16)
}

async function readUserMeCached(token: string): Promise<UserPublic> {
  const now = Date.now()
  const fp = tokenFingerprint(token)
  if (
    cachedUser &&
    cachedTokenFingerprint === fp &&
    now - cachedAt < CACHE_TTL
  ) {
    return cachedUser
  }
  const user = await UsersService.readUserMe()
  cachedUser = user
  cachedTokenFingerprint = fp
  cachedAt = now
  return user
}

export function invalidateAdminUserCache() {
  cachedUser = null
  cachedTokenFingerprint = ""
  cachedAt = 0
}

function pathAllowed(pathname: string, prefixes: string[]): boolean {
  // /admin 的 index（用户管理）须精确匹配，前缀匹配会放行全部子路径
  if (pathname === "/admin") return prefixes.includes("/admin")
  return prefixes.some((p) => p !== "/admin" && pathname.startsWith(p))
}

export const Route = createFileRoute("/_layout/admin")({
  beforeLoad: async ({ location }) => {
    const token = localStorage.getItem("access_token")
    const role = localStorage.getItem("esa:role")
    if (!token) {
      invalidateAdminUserCache()
      throw redirect({ to: "/login" })
    }
    // 平台运营：不走学校用户通道（/users/me 对运营 token 401）
    if (role === "operator") {
      if (!pathAllowed(location.pathname, OPERATOR_ALLOWED)) {
        throw redirect({ to: "/admin/dashboard" })
      }
      return
    }
    try {
      const user = await readUserMeCached(token)
      const prefixes =
        user.role === "admin" ? SCHOOL_ADMIN_ALLOWED : TEACHER_ALLOWED
      if (!pathAllowed(location.pathname, prefixes)) {
        throw redirect({ to: "/" })
      }
    } catch (err) {
      if ((err as { redirect?: unknown }).redirect) throw err
      invalidateAdminUserCache()
      throw redirect({ to: "/login" })
    }
  },
  component: () => <Outlet />,
})
