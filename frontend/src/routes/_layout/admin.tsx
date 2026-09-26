import { createFileRoute, Outlet } from "@tanstack/react-router"

/**
 * /admin 的布局路由：用户管理在 index，内容管理在 /admin/passages 等子路由。
 */
export const Route = createFileRoute("/_layout/admin")({
  component: () => <Outlet />,
})
