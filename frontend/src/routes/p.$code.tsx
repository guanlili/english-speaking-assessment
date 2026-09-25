import { createFileRoute, Outlet } from "@tanstack/react-router"

/**
 * /p/$code 的布局路由：练习页在 index，结果页在 /p/$code/result。
 * 文件约定下本文件是这两个子路由的父级，只负责渲染 Outlet。
 */
export const Route = createFileRoute("/p/$code")({
  component: () => <Outlet />,
})
