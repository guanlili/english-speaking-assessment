/**
 * 授权台账 + 版本治理（#517）前端纯函数层。
 *
 * 不触达 React 与网络：来源/状态/操作类型双语文案、发布门禁 422 code 映射、
 * 审计前后值与版本快照字段格式化、到期日本地输入串换算、哈希短值都在这里，
 * node --test 可直接覆盖。后端编码口径见 vocabulary_governance 路由，detail 是
 * 稳定标识，面向用户的提示在前端映射。
 */

import type { BiString } from "@/lib/bi"

/** 来源类型取值（与后端 VOCAB_SOURCE_TYPES 对齐） */
export const VOCAB_SOURCE_TYPES = [
  "self_built",
  "textbook",
  "licensed",
  "ai",
  "demo",
] as const

/** 授权状态取值（与后端 LICENSE_STATUS_* 对齐） */
export const LICENSE_STATUS_NOT_REQUIRED = "not_required"
export const LICENSE_STATUS_ACTIVE = "active"
export const LICENSE_STATUS_EXPIRING = "expiring"
export const LICENSE_STATUS_EXPIRED = "expired"

/** 发布门禁 422 稳定错误码（与后端 LICENSE_ERROR_* 对齐） */
export const LICENSE_ERROR_OWNER_MISSING = "vocabulary_license_owner_missing"
export const LICENSE_ERROR_REF_MISSING = "vocabulary_license_ref_missing"
export const LICENSE_ERROR_EXPIRED = "vocabulary_license_expired"

export const SOURCE_TYPE_LABELS: Record<string, BiString> = {
  self_built: { zh: "自建", en: "Self-built" },
  textbook: { zh: "教材", en: "Textbook" },
  licensed: { zh: "授权引进", en: "Licensed" },
  ai: { zh: "AI 生成", en: "AI-generated" },
  demo: { zh: "演示", en: "Demo" },
}

export function sourceTypeLabel(source: string | null | undefined): BiString {
  if (!source) return SOURCE_TYPE_LABELS.self_built
  return SOURCE_TYPE_LABELS[source] ?? { zh: source, en: source }
}

/** 是否演示/mock 来源：页面须标注「仅本地演示，不用于生产」。 */
export function isDemoSource(source: string | null | undefined): boolean {
  return source === "demo"
}

export const LICENSE_STATUS_LABELS: Record<string, BiString> = {
  [LICENSE_STATUS_NOT_REQUIRED]: { zh: "无需授权", en: "Not required" },
  [LICENSE_STATUS_ACTIVE]: { zh: "有效", en: "Active" },
  [LICENSE_STATUS_EXPIRING]: { zh: "临期", en: "Expiring soon" },
  [LICENSE_STATUS_EXPIRED]: { zh: "已过期", en: "Expired" },
}

export function licenseStatusLabel(
  status: string | null | undefined,
): BiString {
  if (!status) return LICENSE_STATUS_LABELS[LICENSE_STATUS_NOT_REQUIRED]
  return LICENSE_STATUS_LABELS[status] ?? { zh: status, en: status }
}

/** 授权台账可编辑字段 → 双语文案（与后端 LICENSE_FIELDS 对齐）。 */
export const LICENSE_FIELD_LABELS: Record<string, BiString> = {
  source_type: { zh: "来源类型", en: "Source type" },
  license_owner: { zh: "授权方", en: "License owner" },
  license_ref: { zh: "凭证（文号 / 链接）", en: "License ref (no. / URL)" },
  license_expires_at: { zh: "到期日", en: "Expires at" },
  authorization_doc_url: { zh: "授权书链接", en: "Authorization doc URL" },
  license_note: { zh: "备注", en: "Note" },
}

/** 版本操作类型双语文案（与后端 VERSION_ACTION_* 对齐）。 */
export const VERSION_ACTION_LABELS: Record<string, BiString> = {
  create: { zh: "初始创建", en: "Created" },
  add_words: { zh: "加词", en: "Words added" },
  remove_word: { zh: "删词", en: "Word removed" },
  edit_word: { zh: "编辑词条", en: "Word edited" },
  review: { zh: "审核", en: "Review" },
  rollback: { zh: "回滚", en: "Rollback" },
}

export function versionActionLabel(
  action: string | null | undefined,
): BiString {
  if (!action) return { zh: "其他", en: "Other" }
  return VERSION_ACTION_LABELS[action] ?? { zh: action, en: action }
}

/** 版本对比维度（与后端 _DIFF_FIELD_GROUPS 的键对齐）。 */
export const DIFF_DIMENSION_LABELS: Record<string, BiString> = {
  headword: { zh: "词形", en: "Headword" },
  meaning: { zh: "释义", en: "Meaning" },
  example: { zh: "例句", en: "Example" },
  morphology: { zh: "词法", en: "Morphology" },
}

export function diffDimensionLabel(dimension: string): BiString {
  return DIFF_DIMENSION_LABELS[dimension] ?? { zh: dimension, en: dimension }
}

/** 解析 `code:<n>` 计数参数；非有限非负数字返回 null（与内容治理同口径）。 */
function parseDetailCount(detail: unknown, prefix: string): number | null {
  if (typeof detail !== "string") return null
  const needle = `${prefix}:`
  if (!detail.startsWith(needle)) return null
  const arg = detail.slice(needle.length)
  const n = Number(arg)
  return Number.isFinite(n) && n >= 0 ? n : null
}

/**
 * 发布门禁 422 detail 映射：`code:<n>` 三类授权错误 → 双语文案；
 * 不匹配返回 null，调用方回落通用提示。计数缺失时不给数字。
 */
export function describeLicensePublishError(detail: unknown): BiString | null {
  const ownerCount = parseDetailCount(detail, LICENSE_ERROR_OWNER_MISSING)
  if (ownerCount !== null) {
    return {
      zh:
        ownerCount > 0
          ? `有 ${ownerCount} 个词库或词条缺少授权方：教材 / 授权来源必须填写授权方。`
          : "缺少授权方：教材 / 授权来源必须填写授权方。",
      en:
        ownerCount > 0
          ? `${ownerCount} books/words are missing the license owner (required for textbook / licensed sources).`
          : "Missing license owner (required for textbook / licensed sources).",
    }
  }
  const refCount = parseDetailCount(detail, LICENSE_ERROR_REF_MISSING)
  if (refCount !== null) {
    return {
      zh:
        refCount > 0
          ? `有 ${refCount} 个词库或词条缺少凭证：需填写授权文号或授权书链接。`
          : "缺少凭证：需填写授权文号或授权书链接。",
      en:
        refCount > 0
          ? `${refCount} books/words are missing the license ref (authorization no. or doc URL).`
          : "Missing license ref (authorization no. or doc URL).",
    }
  }
  const expiredCount = parseDetailCount(detail, LICENSE_ERROR_EXPIRED)
  if (expiredCount !== null) {
    return {
      zh:
        expiredCount > 0
          ? `有 ${expiredCount} 个词库或词条授权已过期：请更新有效期后再发布。`
          : "授权已过期：请更新有效期后再发布。",
      en:
        expiredCount > 0
          ? `${expiredCount} books/words have an expired license — update the expiry before publishing.`
          : "License expired — update the expiry before publishing.",
    }
  }
  return null
}

/** 内容哈希短值：取前 8 位，空值回落占位。 */
export function shortHash(hash: string | null | undefined, length = 8): string {
  if (!hash) return "–"
  return hash.slice(0, length)
}

function asText(value: unknown): string | null {
  if (value === null || value === undefined) return null
  if (typeof value === "string") return value.trim() || null
  return String(value)
}

function asTextList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter((item) => item.length > 0)
}

/** 通用查询错误 → 双语文案（403 权限不足 / 404 不存在 / 其余回落重试）。 */
export function describeQueryError(status: number | undefined): BiString {
  if (status === 403) {
    return {
      zh: "没有权限查看这些授权或版本信息。",
      en: "No permission to view this license or version history.",
    }
  }
  if (status === 404) {
    return {
      zh: "内容不存在或已被移除。",
      en: "Not found or already removed.",
    }
  }
  return {
    zh: "加载失败，请重试。",
    en: "Failed to load — please retry.",
  }
}

/** 版本快照条目里某个对比维度的展示值（未知维度回落词形）。 */
export function formatSnapshotField(
  entry: Record<string, unknown> | null | undefined,
  dimension: string,
): string {
  if (!entry) return "–"
  switch (dimension) {
    case "headword":
      return asText(entry.headword) ?? "–"
    case "meaning": {
      const zh = asText(entry.meaning_zh)
      const en = asText(entry.meaning_en)
      return [zh, en].filter(Boolean).join(" / ") || "–"
    }
    case "example":
      return asText(entry.example_en) ?? "–"
    case "morphology": {
      const parts: string[] = []
      const pos = asText(entry.part_of_speech)
      if (pos) parts.push(pos)
      parts.push(...asTextList(entry.accepted_spellings))
      const rawMorphology = Array.isArray(entry.morphology)
        ? entry.morphology
        : []
      const morphology = rawMorphology
        .map((item) => {
          // morphology 记录为 { text, gloss, kind }；兼容纯字符串
          if (typeof item === "string") return item.trim()
          if (item && typeof item === "object") {
            return asText((item as { text?: unknown }).text) ?? ""
          }
          return ""
        })
        .filter((item) => item.length > 0)
      parts.push(...morphology)
      return parts.join(" · ") || "–"
    }
    default:
      return asText(entry.headword) ?? "–"
  }
}

/** 审计变更行视图：字段标签 + 前后值（null 表示清空）。 */
export interface AuditChangeView {
  field: string
  label: BiString
  from: string | null
  to: string | null
}

export function formatAuditChanges(
  changes: Record<string, Record<string, string | null>> | undefined,
): AuditChangeView[] {
  if (!changes) return []
  return Object.entries(changes).map(([field, pair]) => ({
    field,
    label: LICENSE_FIELD_LABELS[field] ?? { zh: field, en: field },
    from: pair?.from ?? null,
    to: pair?.to ?? null,
  }))
}

/** ISO 时间串 → datetime-local 输入值（本地时区，秒以下截掉）；无效值回落空串。 */
export function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return ""
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ""
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** datetime-local 输入值 → ISO 串；空串返回 null（清空）。 */
export function localInputToIso(local: string): string | null {
  const trimmed = local.trim()
  if (!trimmed) return null
  const date = new Date(trimmed)
  if (Number.isNaN(date.getTime())) return null
  return date.toISOString()
}
