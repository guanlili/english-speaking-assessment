import { createFileRoute, redirect } from "@tanstack/react-router"

import { cachedRole } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/")({
  beforeLoad: () => {
    // 运营会话不进教学工作台（校内端点对其 401，进首页会被登出）——
    // Logo 等指向 / 的入口直接落运营大盘
    if (cachedRole() === "operator") {
      throw redirect({ to: "/admin/dashboard" })
    }
    throw redirect({ to: "/classrooms" })
  },
})
