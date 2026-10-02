/**
 * 词汇 CSV 导入预览的问题行原因 → 双语展示。
 *
 * 后端 `_parse_vocab_csv` 的 reason 是中文稳定标识（同 detail 口径），
 * 按规范不在后端做多语言；前端在这里映射成双语，英文界面（外教）
 * 也能看懂词条为何被跳过。未匹配的 reason 原样回落。
 */
import type { BiString } from "./bi.ts"

export function localizeImportIssue(reason: string): BiString {
  if (reason.startsWith("缺少单词")) {
    return { zh: reason, en: "Missing headword" }
  }
  const tooLong = reason.match(/^单词超长：(.+)$/)
  if (tooLong) {
    return { zh: reason, en: `Word too long: ${tooLong[1]}` }
  }
  const noMeaning = reason.match(/^(.+?) 缺少中文释义/)
  if (noMeaning) {
    return {
      zh: reason,
      en: `${noMeaning[1]}: missing Chinese meaning (meaning_zh)`,
    }
  }
  const duplicate = reason.match(/^(.+?) 与前文重复$/)
  if (duplicate) {
    return { zh: reason, en: `${duplicate[1]}: duplicate of an earlier row` }
  }
  return { zh: reason, en: reason }
}
