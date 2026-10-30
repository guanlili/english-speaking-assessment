/**
 * 0.99 客户端错误兼容类：新版内联 client-fetch 在错误响应时抛的是
 * 裸响应体（JSON 对象），不是错误实例。main.tsx 的错误拦截器统一把
 * 抛出值包装成本类，业务侧 `instanceof ApiError` / `.status` / `.body`
 * / `.url` 的既有用法全部保持不变（约 30 个文件依赖此形态，401 登出
 * 等语义承重）。
 */
export class ApiError extends Error {
  readonly status: number
  readonly body: unknown
  readonly url: string

  constructor(status: number, body: unknown, url = "") {
    const detail = (body as { detail?: unknown } | null)?.detail
    super(typeof detail === "string" ? detail : `API error ${status}`)
    this.name = "ApiError"
    this.status = status
    this.body = body
    this.url = url
  }
}
