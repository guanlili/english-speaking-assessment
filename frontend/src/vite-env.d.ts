/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string
  /** 前端 Sentry DSN：未配置时错误上报关闭 */
  readonly VITE_SENTRY_DSN?: string
  /** 对外支持邮箱：未配置时公开页不展示邮件入口，只提示联系学校平台管理员 */
  readonly VITE_SUPPORT_EMAIL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
