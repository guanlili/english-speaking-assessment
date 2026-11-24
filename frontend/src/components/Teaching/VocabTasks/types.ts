/** 词汇任务发布面板共用类型（CSV 导入预览）。 */

import type { VocabularyWordIn } from "@/client"

/** CSV 预览行（导入确认用；保留全部支持字段，避免 meaning_en/example_en/morphology 静默丢失） */
export type BookWordInput = {
  headword: string
  part_of_speech?: string | null
  meaning_zh: string
  meaning_en?: string | null
  accepted_spellings?: Array<string> | null
  example_en?: string | null
  morphology?: Array<Record<string, string>> | null
}

/** 后端预览行 → 建库/加词请求体：单一映射入口，防止字段透传再次漏项。 */
export function toBookWordInput(word: VocabularyWordIn): BookWordInput {
  return {
    headword: word.headword,
    part_of_speech: word.part_of_speech ?? null,
    meaning_zh: word.meaning_zh,
    meaning_en: word.meaning_en ?? null,
    accepted_spellings: word.accepted_spellings ?? null,
    example_en: word.example_en ?? null,
    morphology: word.morphology ?? null,
  }
}

/** CSV 预览结果：有效词 + 无效行 + 文件内重复行（确认前让教师看清会跳过哪些） */
export type VocabCsvPreview = {
  words: BookWordInput[]
  invalid: Array<{ line: number; reason: string }>
  duplicates: Array<{ line: number; reason: string }>
}
