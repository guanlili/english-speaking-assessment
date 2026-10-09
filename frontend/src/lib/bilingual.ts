/** 双语文案工具（批次10）：模型建议支持 {zh, en} 结构，兼容旧纯字符串。 */

export interface BilingualAdvice {
  zh?: string
  en?: string
}

/**
 * 按当前语言取双语建议；无对应语言时回退展示另一种（明确原文 fallback，
 * 不伪造翻译）。
 */
export function adviceText(
  item: string | BilingualAdvice,
  lang: "zh" | "en",
): string {
  if (typeof item === "string") return item
  const preferred = item[lang]
  if (preferred) return preferred
  return item.zh ?? item.en ?? ""
}
