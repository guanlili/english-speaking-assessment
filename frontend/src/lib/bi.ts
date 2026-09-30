/**
 * 双语纯函数部分（无 JSX，node --test 可直接测）。
 * 组件侧的 Provider/hook 见 i18n.tsx。全站双语准则见 CLAUDE.md。
 */

export type Lang = "zh" | "en"

/** 双语文案：全站用户可见字符串的统一形态 */
export interface BiString {
  zh: string
  en: string
}

/** 纯函数解析（便于单测与非组件场景复用） */
export function resolveBi(bi: BiString, lang: Lang): string {
  return bi[lang]
}
