import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"

import {
  type Body_login_login_access_token as AccessToken,
  LoginService,
  type UserPublic,
  type UserRegister,
  UsersService,
} from "@/client"
import { lastJoinedCode } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"
import useCustomToast from "./useCustomToast"

const isLoggedIn = () => {
  return localStorage.getItem("access_token") !== null
}

/** 登录角色（login 时缓存；仅用于路由分流，权限判定在服务端） */
export const cachedRole = (): string | null => localStorage.getItem("esa:role")

export const isStudentLoggedIn = () =>
  isLoggedIn() && cachedRole() === "student"

/** 批量导入的初始密码：首登需要先改密 */
export const mustChangePassword = () =>
  localStorage.getItem("esa:must-change-pw") === "1"

const useAuth = () => {
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const { data: user } = useQuery<UserPublic | null, Error>({
    queryKey: ["currentUser"],
    queryFn: UsersService.readUserMe,
    enabled: isLoggedIn(),
    staleTime: 5 * 60 * 1000,
  })

  const signUpMutation = useMutation({
    mutationFn: (data: UserRegister) =>
      UsersService.registerUser({ requestBody: data }),
    onSuccess: () => {
      navigate({ to: "/login" })
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const login = async (data: AccessToken) => {
    const response = await LoginService.loginAccessToken({
      formData: data,
    })
    localStorage.setItem("access_token", response.access_token)
    // 角色与改密标记随登录缓存，供路由分流（学生/教师互斥登录）
    try {
      const me = await UsersService.readUserMe()
      localStorage.setItem("esa:role", me.role ?? "teacher")
      localStorage.setItem(
        "esa:must-change-pw",
        me.must_change_password ? "1" : "0",
      )
      return me
    } catch {
      // readUserMe 失败（网络等）：清除 token，避免半认证状态
      localStorage.removeItem("access_token")
      throw new Error(
        t({
          zh: "登录后获取用户信息失败，请重试",
          en: "Failed to load your profile after sign-in, please retry",
        }),
      )
    }
  }

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: (me) => {
      if (me.must_change_password) {
        // 批量导入的初始密码：先改密再进任何功能
        navigate({ to: "/change-password" })
        return
      }
      if (me.role === "student") {
        const code = lastJoinedCode()
        navigate({
          to: code ? "/home/$code" : "/join",
          params: code ? { code } : undefined,
        })
      } else {
        navigate({ to: "/" })
      }
    },
    onError: (err) => showErrorToast(extractErrorMessage(err)),
  })

  const logout = () => {
    localStorage.removeItem("access_token")
    localStorage.removeItem("esa:role")
    localStorage.removeItem("esa:must-change-pw")
    // 学生课堂记录一并清除（教师/学生互斥登录，切换身份不留旧档案）
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith("esa:student:")) localStorage.removeItem(key)
    }
    // 停掉任何正在播放的语音（退出后不应继续发声）
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel()
    }
    queryClient.cancelQueries()
    queryClient.invalidateQueries({ queryKey: ["currentUser"] })
    navigate({ to: "/login" })
  }

  return {
    signUpMutation,
    loginMutation,
    logout,
    user,
  }
}

export { isLoggedIn }
export default useAuth
