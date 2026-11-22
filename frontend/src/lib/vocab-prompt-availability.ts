import type { VocabularyWordPublic } from "@/client"
import type { BiString } from "@/lib/bi"

/**
 * 自主练习四类新玩法的「素材可用性」前端预判。
 *
 * 口径与后端 `services/vocabulary_prompt_types.py` 的 `word_supports_prompt_type`
 * 保持一致：开练前在前端先算一遍每类可出题词数，素材不足的题型直接禁用并说明，
 * 不静默回退；后端仍会在创建会话时二次校验（422）。
 */

/** 自主练习可选的四类新玩法（顺序即页面展示顺序） */
export const SELF_PROMPT_TYPES = ["en_zh", "zh_en", "cloze", "roots"] as const
export type SelfPromptType = (typeof SELF_PROMPT_TYPES)[number]

/** 四选一最少词数：正确项 + 3 个干扰项（与后端 MIN_CHOICE_WORDS 一致） */
export const MIN_CHOICE_WORDS = 4

const MORPH_KINDS = new Set(["prefix", "root", "suffix"])

interface MorphSegment {
  text: string
  gloss: string
  kind: string
}

function normalizeMorphology(raw: unknown): MorphSegment[] {
  if (!Array.isArray(raw)) return []
  const cleaned: MorphSegment[] = []
  for (const part of raw) {
    if (typeof part !== "object" || part === null) return []
    const record = part as Record<string, unknown>
    const text = String(record.text ?? "").trim()
    const gloss = String(record.gloss ?? "").trim()
    const kind = String(record.kind ?? "root")
      .trim()
      .toLowerCase()
    if (!text || !gloss) return []
    cleaned.push({
      text,
      gloss,
      kind: MORPH_KINDS.has(kind) ? kind : "root",
    })
  }
  return cleaned
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

/** 拆解块按序拼回必须等于词形（忽略大小写），否则语素块教的是另一个词 */
export function morphologyAssembles(
  headword: string,
  morphology: MorphSegment[],
): boolean {
  if (morphology.length === 0) return false
  return (
    morphology
      .map((segment) => segment.text)
      .join("")
      .toLowerCase() === headword.toLowerCase()
  )
}

/** 例句含完整词形（词边界 + 忽略大小写）才挖空；不含原形返回 null */
export function buildClozeSentence(
  headword: string,
  exampleEn: string | null | undefined,
): string | null {
  if (!exampleEn || !headword) return null
  const pattern = new RegExp(`\\b${escapeRegExp(headword)}\\b`, "i")
  if (!pattern.test(exampleEn)) return null
  return exampleEn.replace(pattern, "____")
}

/** 单条词能否出这种题（只判断素材，与任务上下文无关） */
export function wordSupportsPromptType(
  word: VocabularyWordPublic,
  promptType: string,
): boolean {
  switch (promptType) {
    case "en_zh":
    case "zh_en":
      return true
    case "cloze":
      return buildClozeSentence(word.headword, word.example_en) !== null
    case "roots": {
      const morphology = normalizeMorphology(word.morphology)
      return (
        morphology.length >= 2 && morphologyAssembles(word.headword, morphology)
      )
    }
    default:
      return false
  }
}

/** 每种题型当前词库可出题的词条数 */
export function countEligibleByPromptType(
  words: VocabularyWordPublic[],
): Record<SelfPromptType, number> {
  const counts: Record<SelfPromptType, number> = {
    en_zh: 0,
    zh_en: 0,
    cloze: 0,
    roots: 0,
  }
  for (const word of words) {
    for (const type of SELF_PROMPT_TYPES) {
      if (wordSupportsPromptType(word, type)) counts[type] += 1
    }
  }
  return counts
}

/** 选择题干扰项门槛：词库至少 4 词（正确项 + 3 干扰） */
export function choicePoolSufficient(words: VocabularyWordPublic[]): boolean {
  return words.length >= MIN_CHOICE_WORDS
}

/**
 * 开练 422 原因 → 双语文案。后端 detail 是稳定中文标识，这里按关键词分流，
 * 不把 detail 直接抛给学生；三类已知原因分别对应：缺例句 / 缺词法拆解 / 词数不足 4。
 */
export function describeSelfSession422(detail: string): BiString {
  if (/语境填空|cloze/i.test(detail)) {
    return {
      zh: "所选词条都没有带本词的例句，无法出语境填空；请去掉语境填空，或换一个词库。",
      en: "No word has an example sentence containing it, so Fill-in-the-blank can't be offered. Turn it off or pick another book.",
    }
  }
  if (/词根拼装|roots/i.test(detail)) {
    return {
      zh: "所选词条都没有能拼回原词的词法拆解，无法出词根拼装；请去掉词根拼装，或换一个词库。",
      en: "No word has word parts that assemble back to the whole word, so Word Parts can't be offered. Turn it off or pick another book.",
    }
  }
  if (/选择题至少|干扰项/.test(detail)) {
    return {
      zh: "选择题至少需要 4 个词才能生成干扰项；请增加词量，或去掉选择题。",
      en: "Choice questions need at least 4 words for distractors. Add more words or turn off the choice types.",
    }
  }
  return {
    zh: "开练被拒绝：请检查题型与词库选择后重试。",
    en: "Couldn't start the round — check your prompt types and book, then retry.",
  }
}
