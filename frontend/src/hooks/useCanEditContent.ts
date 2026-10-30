import { useQuery } from "@tanstack/react-query"

import { type UserPublic, UsersService } from "@/client"

/**
 * 题库归属：创建者与管理员可改/删；owner_id 为空的公共内容所有教师可改。
 * 仅用于隐藏不可用的按钮，权限以服务端为准。
 */
export function useCanEditContent(): (ownerId?: string | null) => boolean {
  const { data: user } = useQuery<UserPublic | null, Error>({
    queryKey: ["currentUser"],
    queryFn: () => UsersService.readUserMe(),
    enabled: localStorage.getItem("access_token") !== null,
    staleTime: 5 * 60 * 1000,
  })
  return (ownerId) =>
    !ownerId || user?.is_superuser === true || ownerId === user?.id
}
