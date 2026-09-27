import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"

import { isLoggedIn } from "@/hooks/useAuth"

/**
 * /t/$code 的布局路由：面板在 index，学生详情在 /t/$code/s/$studentId。
 */
export const Route = createFileRoute("/t/$code")({
  beforeLoad: () => {
    if (!isLoggedIn()) throw redirect({ to: "/login" })
  },
  component: () => <Outlet />,
})
