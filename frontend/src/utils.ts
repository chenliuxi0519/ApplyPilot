import { AxiosError } from "axios"
import type { ApiError } from "./client"

function extractErrorMessage(err: ApiError): string {
  if (err instanceof AxiosError) {
    return "网络请求失败，请检查连接后重试。"
  }

  const errDetail = (err.body as any)?.detail
  if (Array.isArray(errDetail) && errDetail.length > 0) {
    return translateErrorMessage(errDetail[0].msg)
  }
  return translateErrorMessage(errDetail)
}

const ERROR_TRANSLATIONS: Record<string, string> = {
  // 兼容历史响应和未升级的后端实例。
  "Incorrect email or password": "邮箱或密码错误",
  "New password cannot be the same as the current one":
    "新密码不能与当前密码相同",
  "User with this email already exists in the system": "该邮箱已被注册",
  "Could not validate credentials": "登录状态已失效，请重新登录",
  "Inactive user": "该账户已停用",
  "Profile not found": "尚未建立个人档案",
}

function translateErrorMessage(message: unknown): string {
  if (typeof message !== "string" || !message.trim())
    return "出现了问题，请稍后重试。"
  if (ERROR_TRANSLATIONS[message]) return ERROR_TRANSLATIONS[message]
  return /[\u3400-\u9fff]/.test(message)
    ? message
    : "操作失败，请检查输入后重试。"
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
