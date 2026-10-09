import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Suspense, useEffect, useState } from "react"
import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { DataTable } from "@/components/Common/DataTable"
import PendingUsers from "@/components/Pending/PendingUsers"
import { APP_NAME } from "@/config"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

const USERS_PAGE_SIZE = 25

function getUsersQueryOptions(pageIndex: number, pageSize: number) {
  return {
    queryFn: () =>
      UsersService.readUsers({ skip: pageIndex * pageSize, limit: pageSize }),
    // 页码与每页条数进 key：切页翻新请求；前缀 ["users"] 仍覆盖增删改失效
    queryKey: ["users", pageIndex, pageSize],
    placeholderData: keepPreviousData,
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
  // 服务端分页（批次09）：此前固定取前 100 人，超出部分无法从本页管理
  const [pageIndex, setPageIndex] = useState(0)
  const [pageSize, setPageSize] = useState(USERS_PAGE_SIZE)
  const { data: users, isFetching } = useQuery(
    getUsersQueryOptions(pageIndex, pageSize),
  )

  // 删除末页最后一人后回退到仍有数据的一页（失效后本页数据为空）
  useEffect(() => {
    if (users && users.data.length === 0 && users.count > 0 && pageIndex > 0) {
      setPageIndex(Math.max(0, Math.ceil(users.count / pageSize) - 1))
    }
  }, [users, pageIndex, pageSize])

  const tableData: UserTableData[] = (users?.data ?? []).map(
    (user: UserPublic) => ({
      ...user,
      isCurrentUser: currentUser?.id === user.id,
    }),
  )

  return (
    <DataTable
      columns={columns}
      data={tableData}
      manualPagination={{
        rowCount: users?.count ?? 0,
        pageIndex,
        pageSize,
        onPageChange: setPageIndex,
        onPageSizeChange: (next) => {
          setPageSize(next)
          setPageIndex(0)
        },
        loading: isFetching,
      }}
    />
  )
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
