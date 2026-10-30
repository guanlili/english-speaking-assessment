/**
 * API 客户端启动配置：应用入口（main.tsx）与 e2e fixture 入口共用。
 * 0.99 客户端的 throwOnError/拦截器必须在使用前显式配置——旧客户端
 * 错误天生 reject、token 自动附带，新客户端全部依赖这里的初始化。
 * fixture 页不走 main.tsx，漏掉这段会让错误静默 resolve（测试挂错形态）。
 */
import { client } from "@/client"
import { ApiError } from "@/lib/api-error"

let configured = false

export function setupApiClient(): void {
  if (configured) return
  configured = true
  // 生产部署由流水线注入空串（同源相对路径）；未注入时显式回退空串——
  // undefined 会让客户端拼出 /undefined/api/... 全 404。throwOnError/
  // responseStyle 与生成代码的泛型默认值（generate-client.sh 后处理为
  // true）保持一致：await 直接拿数据、错误抛 ApiError。
  client.setConfig({
    baseUrl: import.meta.env.VITE_API_URL ?? "",
    throwOnError: true,
    responseStyle: "data",
  })
  client.interceptors.request.use((request) => {
    const token = localStorage.getItem("access_token")
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`)
    }
    return request
  })
  // 0.99 内联 client-fetch 错误时抛裸响应体：统一包装成 ApiError 兼容类，
  // 全站 instanceof/.status/.body/.url 判断（含 401 登出）保持原语义
  client.interceptors.error.use((error, response, request) => {
    if (error instanceof ApiError) return error
    return new ApiError(response?.status ?? 0, error, request?.url ?? "")
  })
}
