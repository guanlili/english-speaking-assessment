import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { RefreshCw, Search } from "lucide-react"
import { Suspense, useEffect, useState } from "react"
import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { DataTable } from "@/components/Common/DataTable"
import PendingUsers from "@/components/Pending/PendingUsers"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { APP_NAME } from "@/config"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

const USERS_PAGE_SIZE = 25

function getUsersQueryOptions(
  pageIndex: number,
  pageSize: number,
  q: string,
  role: string,
) {
  return {
    queryFn: () =>
      UsersService.readUsers({
        skip: pageIndex * pageSize,
        limit: pageSize,
        q: q || undefined,
        role: role || undefined,
      }),
    // 页码与每页条数进 key：切页翻新请求；前缀 ["users"] 仍覆盖增删改失效
    queryKey: ["users", pageIndex, pageSize, q, role],
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
  const { t } = useI18n()
  // 服务端分页（批次09）：此前固定取前 100 人，超出部分无法从本页管理
  const [pageIndex, setPageIndex] = useState(0)
  const [pageSize, setPageSize] = useState(USERS_PAGE_SIZE)
  // 搜索/筛选（服务端 q/role；输入防抖 350ms）
  const [searchInput, setSearchInput] = useState("")
  const [search, setSearch] = useState("")
  const [role, setRole] = useState("all")
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim())
      setPageIndex(0)
    }, 350)
    return () => clearTimeout(timer)
  }, [searchInput])
  const {
    data: users,
    isPending,
    isError,
    isPlaceholderData,
    isFetching,
    refetch,
  } = useQuery(
    getUsersQueryOptions(
      pageIndex,
      pageSize,
      search,
      role === "all" ? "" : role,
    ),
  )

  // 删除末页最后一人后回退到仍有数据的一页。只看「当前页」的真实成功
  // 响应：placeholder 旧页（keepPreviousData）与失败响应都不是本页事实，
  // 不能据此跳页（返修R13）
  useEffect(() => {
    if (
      users &&
      !isPlaceholderData &&
      !isError &&
      users.data.length === 0 &&
      users.count > 0 &&
      pageIndex > 0
    ) {
      setPageIndex(Math.max(0, Math.ceil(users.count / pageSize) - 1))
    }
  }, [users, isPlaceholderData, isError, pageIndex, pageSize])

  // useQuery 的常规 pending（非 Suspense）与失败都要有明确界面与恢复入口
  if (isPending) {
    return <PendingUsers />
  }
  if (isError) {
    return (
      <div
        role="alert"
        className="flex flex-col items-start gap-3 rounded-xl border p-6 text-muted-foreground"
      >
        <p>{t({ zh: "用户列表加载失败", en: "Failed to load users" })}</p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => {
              void refetch()
            }}
            className="h-11"
          >
            <RefreshCw className="size-4" />
            {t({ zh: "重试", en: "Retry" })}
          </Button>
          {pageIndex > 0 && (
            <Button
              variant="ghost"
              className="h-11"
              onClick={() => {
                setPageIndex(pageIndex - 1)
              }}
            >
              {t({ zh: "返回上一页", en: "Go back a page" })}
            </Button>
          )}
        </div>
      </div>
    )
  }

  const tableData: UserTableData[] = (users?.data ?? []).map(
    (user: UserPublic) => ({
      ...user,
      isCurrentUser: currentUser?.id === user.id,
    }),
  )

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label={t({ zh: "搜索用户", en: "Search users" })}
            placeholder={t({
              zh: "搜索学号 / 姓名 / 邮箱",
              en: "Search by ID, name, or email",
            })}
            className="pl-9"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
        </div>
        <Select
          value={role}
          onValueChange={(next) => {
            setRole(next)
            setPageIndex(0)
          }}
        >
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              {t({ zh: "全部角色", en: "All Roles" })}
            </SelectItem>
            <SelectItem value="student">
              {t({ zh: "学生", en: "Students" })}
            </SelectItem>
            <SelectItem value="teacher">
              {t({ zh: "教师", en: "Teachers" })}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
      <DataTable
        columns={columns}
        data={tableData}
        // 稳定业务主键：翻页后行位置复用不会让旧行弹窗状态挂到新行（返修R01）
        getRowId={(row) => row.id}
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
    </div>
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
