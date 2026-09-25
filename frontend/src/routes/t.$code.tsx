import { createFileRoute, Outlet } from "@tanstack/react-router"

/**
 * /t/$code 的布局路由：面板在 index，学生详情在 /t/$code/s/$studentId。
 */
export const Route = createFileRoute("/t/$code")({
  component: () => <Outlet />,
})
