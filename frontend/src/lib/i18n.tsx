import {
  type BiString,
  type Lang,
  readStoredLang,
  resolveBi,
  writeStoredLang,
} from "@/lib/bi"

export type { BiString, Lang } from "@/lib/bi"
export { resolveBi } from "@/lib/bi"

/**
 * 平台双语（中文/英文）支持——因为有外教使用，全站用户可见文案都必须双语。
 *
 * 用法（登录页是参考实现）：
 *   const { lang, setLang, t } = useI18n()
 *   t({ zh: "登录", en: "Sign in" })
 *
 * 约定（详见 CLAUDE.md「双语准则」）：
 * - 默认中文（学生主体是中文用户），外教切到英文后按浏览器记忆
 * - 新增用户可见文案必须写成 t({ zh, en })，不允许再落单语言硬编码
 * - 共享术语的中英文以 terms.ts 的术语表为准，翻译时对齐
 * - 后端 API 的 detail 文案是稳定标识（前端有按文案分流的逻辑），
 *   面向用户的错误提示一律在前端映射成双语，不直接展示 detail
 */
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react"

interface I18nContextValue {
  lang: Lang
  setLang: (lang: Lang) => void
  /** t({ zh: "…", en: "…" })：按当前语言取文案 */
  t: (bi: BiString) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readStoredLang)

  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    writeStoredLang(next)
  }, [])

  useEffect(() => {
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN"
  }, [lang])

  const value = useMemo<I18nContextValue>(
    () => ({ lang, setLang, t: (bi: BiString) => resolveBi(bi, lang) }),
    [lang, setLang],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext)
  if (ctx === null) {
    throw new Error(
      "useI18n 必须在 I18nProvider 内使用（__root.tsx 已全局包裹）",
    )
  }
  return ctx
}
