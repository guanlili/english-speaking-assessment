import { AxiosError } from "axios"
import type { ApiError } from "./client"

const AUTH_ERROR_MESSAGES: Record<string, string> = {
  "Incorrect email or password": "邮箱或密码不正确，请重新输入",
  "Inactive user": "账号已停用，请联系学校管理员",
  "Open user registration is forbidden on this server":
    "暂未开放自助注册，请联系学校管理员开通账号",
  "The user with this email already exists in the system":
    "该邮箱已注册，请直接登录或找回密码",
  "Invalid token": "重置链接无效或已过期，请重新申请",
}

export function extractErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    return err.code === "ECONNABORTED"
      ? "请求超时，请稍后重试"
      : "网络连接异常，请检查网络后重试"
  }

  const body = (err as ApiError | null)?.body as
    | { detail?: string | Array<{ msg: string }> }
    | undefined
  const errDetail = body?.detail
  if (Array.isArray(errDetail) && errDetail.length > 0) {
    return errDetail[0].msg
  }
  if (typeof errDetail === "string") {
    return AUTH_ERROR_MESSAGES[errDetail] ?? errDetail
  }
  return "服务暂时不可用，请稍后重试"
}

export const handleError = function (
  this: (msg: string) => void,
  err: ApiError,
) {
  const errorMessage = extractErrorMessage(err)
  this(errorMessage)
}

export const getInitials = (name: string): string => {
  return name
    .split(" ")
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase()
}
