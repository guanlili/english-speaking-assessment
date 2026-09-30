import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Suspense } from "react"
import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { DataTable } from "@/components/Common/DataTable"
import PendingUsers from "@/components/Pending/PendingUsers"
import { APP_NAME } from "@/config"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

function getUsersQueryOptions() {
  return {
    queryFn: () => UsersService.readUsers({ skip: 0, limit: 100 }),
    queryKey: ["users"],
  }
}

export const Route = createFileRoute("/_layout/admin/")({
  component: Admin,
  head: () => ({
    meta: [
      {
        title: `用户与权限 / Users & Permissions - ${APP_NAME}`,
      },
    ],
  }),
})

function UsersTableContent() {
  const { user: currentUser } = useAuth()
  const { data: users } = useSuspenseQuery(getUsersQueryOptions())

  const tableData: UserTableData[] = users.data.map((user: UserPublic) => ({
    ...user,
    isCurrentUser: currentUser?.id === user.id,
  }))

  return <DataTable columns={columns} data={tableData} />
}

function UsersTable() {
  return (
    <Suspense fallback={<PendingUsers />}>
      <UsersTableContent />
    </Suspense>
  )
}

function Admin() {
  const { t } = useI18n()
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {t({ zh: "用户与权限", en: "Users & Permissions" })}
          </h1>
          <p className="text-muted-foreground">
            {t({
              zh: "统一管理平台账号、角色与访问权限",
              en: "Manage platform accounts, roles, and access in one place",
            })}
          </p>
        </div>
        <AddUser />
      </div>
      <UsersTable />
    </div>
  )
}
