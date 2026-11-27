/**
 * AC4 内容治理（审核 / 发布门禁 / 词条编辑）前端纯函数层。
 *
 * 不触达 React 与网络：detail 编码解析、状态/来源双语文案、导入新增/跳过
 * 派生、可发布判定、词法结构校验都在这里，node --test 可直接覆盖。
 * 后端编码口径见 ac4-contract.md，detail 是稳定标识，用户提示在前端映射。
 */

import type { BiString } from "@/lib/bi"

/** 审核状态机取值（与后端 vocabulary_word.review_status 对齐） */
export type ReviewStatus = "draft" | "pending" | "approved" | "rejected"

/** 词条来源取值（与后端 vocabulary_word.source 对齐） */
export type WordSource = "teacher" | "ai" | "textbook" | "demo" | "import"

/** 审核冲突：`review_state_conflict:<n>` */
export const CODE_REVIEW_STATE_CONFLICT = "review_state_conflict"
/** 词条版本冲突：`vocabulary_word_version_conflict`（无参数） */
export const CODE_VERSION_CONFLICT = "vocabulary_word_version_conflict"
/** 同库重复键：`vocabulary_word_duplicate:<headword>` */
export const CODE_DUPLICATE_WORD = "vocabulary_word_duplicate"
/** 发布门禁：`vocabulary_words_not_approved:<n>` */
export const CODE_NOT_APPROVED = "vocabulary_words_not_approved"

/**
 * 解析 `code:arg` 形态的后端 detail。
 * 不匹配前缀、detail 非字符串时返回 null，调用方回落通用提示。
 */
export function parseDetailCode(
  detail: unknown,
  prefix: string,
): string | null {
  if (typeof detail !== "string") return null
  const needle = `${prefix}:`
  if (!detail.startsWith(needle)) return null
  const arg = detail.slice(needle.length)
  return arg.length > 0 ? arg : null
}

/** 解析 `code:<n>` 计数参数；非有限非负数字返回 null。 */
export function parseDetailCount(
  detail: unknown,
  prefix: string,
): number | null {
  const arg = parseDetailCode(detail, prefix)
  if (arg === null) return null
  const n = Number(arg)
  return Number.isFinite(n) && n >= 0 ? n : null
}

/** 审核状态双语文案（未知状态回落“其他 / Other”，不抛原文）。 */
export const REVIEW_STATUS_LABELS: Record<string, BiString> = {
  pending: { zh: "待审", en: "Pending" },
  approved: { zh: "已通过", en: "Approved" },
  rejected: { zh: "已拒绝", en: "Rejected" },
  draft: { zh: "草稿", en: "Draft" },
}

/** 来源双语文案；AI 单独标记，其余按来源归类。 */
export const SOURCE_LABELS: Record<string, BiString> = {
  teacher: { zh: "教师", en: "Teacher" },
  ai: { zh: "AI", en: "AI" },
  textbook: { zh: "教材", en: "Textbook" },
  demo: { zh: "演示", en: "Demo" },
  import: { zh: "导入", en: "Import" },
}

export function reviewStatusLabel(status: string | null | undefined): BiString {
  if (!status) return { zh: "待审", en: "Pending" }
  return REVIEW_STATUS_LABELS[status] ?? { zh: "其他", en: "Other" }
}

export function sourceLabel(source: string | null | undefined): BiString {
  if (!source) return { zh: "教师", en: "Teacher" }
  return SOURCE_LABELS[source] ?? { zh: source, en: source }
}

/** 来源筛选选项（面板下拉用；顺序与契约枚举一致）。 */
export const SOURCE_FILTER_OPTIONS: Array<{
  value: WordSource
  label: BiString
}> = [
  { value: "teacher", label: SOURCE_LABELS.teacher },
  { value: "ai", label: SOURCE_LABELS.ai },
  { value: "textbook", label: SOURCE_LABELS.textbook },
  { value: "demo", label: SOURCE_LABELS.demo },
  { value: "import", label: SOURCE_LABELS.import },
]

/**
 * 导入结果派生：
 * - 新增 = 请求前后词库词数差（下限 0）；
 * - 跳过 = 提交数 − 新增数（下限 0）。
 * 新建词库时 beforeCount 为 null，按 0 起算。
 */
export function deriveImportStats(
  submitted: number,
  beforeCount: number | null | undefined,
  afterCount: number | null | undefined,
): { added: number; skipped: number } {
  const before = beforeCount ?? 0
  const after = afterCount ?? before
  const added = Math.max(0, after - before)
  const skipped = Math.max(0, submitted - added)
  return { added, skipped }
}

/** 可发布 / 可练习词条：未归档且已通过审核。 */
export function isPublishableWord(word: {
  status?: string | null
  review_status?: string | null
}): boolean {
  return word.status !== "archived" && word.review_status === "approved"
}

/** 未通过审核（待审 / 已拒绝 / 草稿）词条数；发布勾词清单之外的提示口径。 */
export function countNotApproved<
  T extends { status?: string | null; review_status?: string | null },
>(words: T[]): number {
  return words.filter((word) => !isPublishableWord(word)).length
}

/** 词法拆解行（与后端 morphology 记录结构对齐：text/gloss/kind）。 */
export interface MorphologyPart {
  text: string
  gloss: string
  kind: string
}

export const MORPHOLOGY_KINDS = [
  { value: "root", label: { zh: "词根", en: "Root" } },
  { value: "prefix", label: { zh: "前缀", en: "Prefix" } },
  { value: "suffix", label: { zh: "后缀", en: "Suffix" } },
] as const

/**
 * 词法结构校验：
 * - 整行留空视为删除该行，不计入提交；
 * - 有内容的行 text 必填；kind 必须落在 root/prefix/suffix；
 * - 任一违规返回双语错误，调用方阻断保存，不静默丢弃词法。
 */
export function validateMorphology(parts: MorphologyPart[]): BiString | null {
  for (const part of parts) {
    const text = part.text.trim()
    const gloss = part.gloss.trim()
    const kind = part.kind.trim()
    if (!text && !gloss && !kind) continue
    if (!text) {
      return {
        zh: "词法拆解缺少片段文本（text），请补全或删除该行。",
        en: "A morphology part is missing its text — complete the row or remove it.",
      }
    }
    if (!MORPHOLOGY_KINDS.some((option) => option.value === kind)) {
      return {
        zh: "词法片段类型需为词根 / 前缀 / 后缀。",
        en: "Morphology kind must be root, prefix, or suffix.",
      }
    }
  }
  return null
}

/** 词法行 → 后端记录：丢弃全空行，字段去空白；空数组回传 null。 */
export function serializeMorphology(
  parts: MorphologyPart[],
): Array<Record<string, string>> | null {
  const rows = parts
    .map((part) => ({
      text: part.text.trim(),
      gloss: part.gloss.trim(),
      kind: part.kind.trim(),
    }))
    .filter((part) => part.text !== "")
  return rows.length > 0 ? rows : null
}
