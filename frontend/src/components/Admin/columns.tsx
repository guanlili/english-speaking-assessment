import type { ColumnDef } from "@tanstack/react-table"

import type { UserPublic } from "@/client"
import { Badge } from "@/components/ui/badge"
import type { useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"
import { UserActionsMenu } from "./UserActionsMenu"

export type UserTableData = UserPublic & {
  isCurrentUser: boolean
}

/** i18n 翻译函数类型（来自 useI18n，避免在非组件处调用 hook） */
type Translate = ReturnType<typeof useI18n>["t"]

/** 用户表列定义工厂（双语）：调用方 useMemo 缓存，语言切换时重建。 */
export function buildUserColumns(t: Translate): ColumnDef<UserTableData>[] {
  return [
    {
      accessorKey: "full_name",
      header: t({ zh: "姓名", en: "Full Name" }),
      cell: ({ row }) => {
        const fullName = row.original.full_name
        return (
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "font-medium",
                !fullName && "text-muted-foreground",
              )}
            >
              {fullName || "N/A"}
            </span>
            {row.original.isCurrentUser && (
              <Badge variant="outline" className="text-xs">
                {t({ zh: "你", en: "You" })}
              </Badge>
            )}
          </div>
        )
      },
    },
    {
      accessorKey: "email",
      header: t({ zh: "邮箱", en: "Email" }),
      cell: ({ row }) => (
        <span className="text-muted-foreground">{row.original.email}</span>
      ),
    },
    {
      accessorKey: "role",
      header: t({ zh: "角色", en: "Role" }),
      cell: ({ row }) => {
        const { role } = row.original
        const isAdmin = role === "admin"
        const isStudent = !isAdmin && role === "student"
        return (
          <Badge
            variant={isAdmin ? "default" : isStudent ? "outline" : "secondary"}
          >
            {isAdmin
              ? t({ zh: "管理员", en: "Admin" })
              : isStudent
                ? t({ zh: "学生", en: "Student" })
                : t({ zh: "教师", en: "Teacher" })}
          </Badge>
        )
      },
    },
    {
      accessorKey: "is_active",
      header: t({ zh: "状态", en: "Status" }),
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "size-2 rounded-full",
              row.original.is_active ? "bg-green-500" : "bg-gray-400",
            )}
          />
          <span
            className={row.original.is_active ? "" : "text-muted-foreground"}
          >
            {row.original.is_active
              ? t({ zh: "启用", en: "Active" })
              : t({ zh: "已禁用", en: "Inactive" })}
          </span>
        </div>
      ),
    },
    {
      id: "actions",
      header: () => (
        <span className="sr-only">{t({ zh: "操作", en: "Actions" })}</span>
      ),
      cell: ({ row }) => (
        <div className="flex justify-end">
          <UserActionsMenu user={row.original} />
        </div>
      ),
    },
  ]
}
