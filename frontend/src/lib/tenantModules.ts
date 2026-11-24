import type {
  ModuleStatus,
  TenantModulePublic,
  TenantUsageMetrics,
} from "@/client"
import type { BiString } from "@/lib/bi"

/**
 * 学校模块授权（#517）的纯函数口径：状态机派生标签、试用提醒阈值、
 * 紧凑用量格式化、范围校验与 CSV 文件名。组件只做展示，判定全部在这里，
 * 便于 node:test 直测与运营端 / 校管后台复用同一口径。
 *
 * 状态枚举与服务端 `entitlement.compute_state` 一一对应；前端不另算状态，
 * 只对后端下发的 `state` 做归一化展示。
 */

export type ModuleState =
  | "not_granted"
  | "disabled"
  | "scheduled"
  | "expired"
  | "active"

export type GrantType = "trial" | "paid" | "manual"

/** 两类后端授权结构（运营列表行 / /modules/me 状态）的结构子集。 */
export interface ModuleLike {
  state?: string | null
  enabled?: boolean
  grant_type?: string | null
  days_left?: number | null
  expires_at?: string | null
  effective_at?: string | null
  starts_at?: string | null
}

/** 后端状态值归一化：未知 / 缺行按未开通处理。 */
export function normalizeState(value?: string | null): ModuleState {
  switch (value) {
    case "disabled":
      return "disabled"
    case "scheduled":
      return "scheduled"
    case "expired":
      return "expired"
    case "active":
      return "active"
    default:
      return "not_granted"
  }
}

/** 授权类型归一化：非 trial/paid 一律按人工（manual）。 */
export function normalizeGrantType(value?: string | null): GrantType {
  return value === "trial" || value === "paid" ? value : "manual"
}

export const STATE_LABELS: Record<ModuleState, BiString> = {
  not_granted: { zh: "未开通", en: "Not granted" },
  disabled: { zh: "已关闭", en: "Closed" },
  scheduled: { zh: "待生效", en: "Scheduled" },
  expired: { zh: "已到期", en: "Expired" },
  active: { zh: "使用中", en: "Active" },
}

export const GRANT_TYPE_LABELS: Record<GrantType, BiString> = {
  trial: { zh: "试用", en: "Trial" },
  paid: { zh: "付费", en: "Paid" },
  manual: { zh: "人工", en: "Manual" },
}

/** 徽标语气：组件映射到 Badge variant / 语义色，不在这里写 Tailwind 类。 */
export type BadgeTone = "muted" | "outline" | "active" | "destructive"

export interface ModuleBadge {
  state: ModuleState
  grant: GrantType
  tone: BadgeTone
  /** 主标签（试用含剩余天数） */
  label: BiString
  /** 次要说明（授权类型），用于 tooltip / 小字 */
  hint: BiString
  daysLeft: number | null
}

function daysLeftOf(m: ModuleLike): number | null {
  return typeof m.days_left === "number" && Number.isFinite(m.days_left)
    ? m.days_left
    : null
}

/** 六态徽标描述：未开通 / 已关闭 / 待生效 / 已到期 / 试用中·剩 N 天 / 使用中。 */
export function describeModuleBadge(
  m: ModuleLike | TenantModulePublic | ModuleStatus | undefined | null,
): ModuleBadge {
  if (!m) {
    return {
      state: "not_granted",
      grant: "manual",
      tone: "muted",
      label: STATE_LABELS.not_granted,
      hint: GRANT_TYPE_LABELS.manual,
      daysLeft: null,
    }
  }
  const state = normalizeState(m.state)
  const grant = normalizeGrantType(m.grant_type)
  const daysLeft = daysLeftOf(m)

  switch (state) {
    case "disabled":
      return {
        state,
        grant,
        tone: "muted",
        label: STATE_LABELS.disabled,
        hint: GRANT_TYPE_LABELS[grant],
        daysLeft,
      }
    case "scheduled":
      return {
        state,
        grant,
        tone: "outline",
        label: STATE_LABELS.scheduled,
        hint: GRANT_TYPE_LABELS[grant],
        daysLeft,
      }
    case "expired":
      return {
        state,
        grant,
        tone: "destructive",
        label: STATE_LABELS.expired,
        hint: GRANT_TYPE_LABELS[grant],
        daysLeft,
      }
    case "active": {
      if (grant === "trial") {
        const label: BiString =
          daysLeft === null
            ? { zh: "试用中", en: "Trial" }
            : {
                zh: `试用中 · 剩 ${daysLeft} 天`,
                en: `Trial · ${daysLeft} days left`,
              }
        return {
          state,
          grant,
          tone: "active",
          label,
          hint: GRANT_TYPE_LABELS.trial,
          daysLeft,
        }
      }
      return {
        state,
        grant,
        tone: "active",
        label: STATE_LABELS.active,
        hint: GRANT_TYPE_LABELS[grant],
        daysLeft,
      }
    }
    default:
      return {
        state: "not_granted",
        grant,
        tone: "muted",
        label: STATE_LABELS.not_granted,
        hint: GRANT_TYPE_LABELS[grant],
        daysLeft,
      }
  }
}

/* ------------------------------------------------------------------ */
/* 校管后台到期提醒横幅                                                 */
/* ------------------------------------------------------------------ */

export type BannerLevel = "none" | "trial" | "warning" | "critical" | "expired"

/** 试用提醒档位：≤30 天提示，≤7 天警示，≤1 天紧急。 */
export const TRIAL_REMIND_DAYS = 30
export const TRIAL_WARN_DAYS = 7
export const TRIAL_CRITICAL_DAYS = 1

export interface BannerEntry {
  level: BannerLevel
  daysLeft: number | null
  state: ModuleState
  grant: GrantType
}

/**
 * 横幅判定：
 * - expired → 到期横幅；
 * - disabled / not_granted / scheduled 不提示；
 * - active + trial 且有剩余天数，按 30 / 7 / 1 三档；其余不提示。
 */
export function describeBanner(
  m: ModuleLike | TenantModulePublic | ModuleStatus | undefined | null,
): BannerEntry {
  if (!m)
    return {
      level: "none",
      daysLeft: null,
      state: "not_granted",
      grant: "manual",
    }
  const state = normalizeState(m.state)
  const grant = normalizeGrantType(m.grant_type)
  const daysLeft = daysLeftOf(m)

  if (state === "expired") {
    return { level: "expired", daysLeft, state, grant }
  }
  if (state !== "active" || grant !== "trial" || daysLeft === null) {
    return { level: "none", daysLeft, state, grant }
  }
  if (daysLeft <= TRIAL_CRITICAL_DAYS) {
    return { level: "critical", daysLeft, state, grant }
  }
  if (daysLeft <= TRIAL_WARN_DAYS) {
    return { level: "warning", daysLeft, state, grant }
  }
  if (daysLeft <= TRIAL_REMIND_DAYS) {
    return { level: "trial", daysLeft, state, grant }
  }
  return { level: "none", daysLeft, state, grant }
}

/* ------------------------------------------------------------------ */
/* 按校用量：九项指标与紧凑格式                                         */
/* ------------------------------------------------------------------ */

export const USAGE_METRICS = [
  { key: "active_teachers", zh: "活跃教师", en: "Teachers" },
  { key: "active_students", zh: "活跃学生", en: "Students" },
  { key: "vocab_answers", zh: "词汇作答", en: "Answers" },
  { key: "published_tasks", zh: "发布任务", en: "Tasks" },
  { key: "completed_students", zh: "完成任务人数", en: "Completed" },
  { key: "pk_matches", zh: "PK 对局", en: "PK matches" },
  { key: "farm_harvests", zh: "农场收获（下限）", en: "Farm harvests (min.)" },
  { key: "placement_tests", zh: "Placement 测试", en: "Placement tests" },
  { key: "exports", zh: "导出次数", en: "Exports" },
] as const

export type UsageMetricKey = (typeof USAGE_METRICS)[number]["key"]

export function metricValue(
  metrics: TenantUsageMetrics | null | undefined,
  key: UsageMetricKey,
): number {
  const value = metrics?.[key]
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

/** 列表紧凑两行用到的五项核心指标。 */
export interface CompactUsage {
  teachers: number
  students: number
  answers: number
  tasks: number
  completed: number
}

export function readCompactUsage(
  metrics: TenantUsageMetrics | null | undefined,
): CompactUsage {
  return {
    teachers: metricValue(metrics, "active_teachers"),
    students: metricValue(metrics, "active_students"),
    answers: metricValue(metrics, "vocab_answers"),
    tasks: metricValue(metrics, "published_tasks"),
    completed: metricValue(metrics, "completed_students"),
  }
}

/* ------------------------------------------------------------------ */
/* 日期范围（本地 YYYY-MM-DD，含当天）                                  */
/* ------------------------------------------------------------------ */

export const USAGE_RANGE_MAX_DAYS = 366

function pad(n: number): string {
  return String(n).padStart(2, "0")
}

export function toDateInput(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** 默认近 30 天（含今天）。 */
export function defaultUsageRange(
  days = 30,
  now: Date = new Date(),
): { from: string; to: string } {
  const to = new Date(now)
  const from = new Date(now)
  from.setDate(from.getDate() - (days - 1))
  return { from: toDateInput(from), to: toDateInput(to) }
}

export type RangeValidation = "ok" | "missing" | "invalid" | "too_wide"

function parseDay(day: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null
  const d = new Date(`${day}T00:00:00`)
  return Number.isNaN(d.getTime()) ? null : d
}

/** 校验范围：日期合法、from ≤ to、跨度 ≤366 天。 */
export function validateUsageRange(from: string, to: string): RangeValidation {
  if (!from || !to) return "missing"
  const fromDate = parseDay(from)
  const toDate = parseDay(to)
  if (!fromDate || !toDate) return "invalid"
  if (fromDate > toDate) return "invalid"
  const spanDays = Math.round(
    (toDate.getTime() - fromDate.getTime()) / (24 * 60 * 60 * 1000),
  )
  if (spanDays > USAGE_RANGE_MAX_DAYS) return "too_wide"
  return "ok"
}

/** CSV 下载文件名：`tenant-<slug>-usage-<from>-<to>.csv`。 */
export function usageCsvFilename(
  slug: string,
  from: string,
  to: string,
): string {
  const safeSlug =
    (slug || "school")
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/^-+|-+$/g, "") || "school"
  const fromPart = from || "all"
  const toPart = to || "all"
  return `tenant-${safeSlug}-usage-${fromPart}-${toPart}.csv`
}

/* ------------------------------------------------------------------ */
/* 模块授权表单（客户端校验，与服务端 422 口径一致）                     */
/* ------------------------------------------------------------------ */

export interface ModuleFormDraft {
  enabled: boolean
  /** datetime-local 原值；空 = 立即生效 */
  effective: string
  /** datetime-local 原值；空 = 长期 */
  expires: string
  grant_type: GrantType
}

export interface ModuleFormResult {
  effective_at: string | null
  expires_at: string | null
  grant_type: GrantType
  error: BiString | null
}

/**
 * 表单校验与出参：
 * - trial 必须填到期时间；
 * - 到期时间必须晚于开始时间（两者都填时）；
 * - 空到期显式转 `null`（长期），空开始转 `null`（立即）。
 */
export function validateModuleForm(draft: ModuleFormDraft): ModuleFormResult {
  const effective_at = draft.effective
    ? new Date(draft.effective).toISOString()
    : null
  const expires_at = draft.expires
    ? new Date(draft.expires).toISOString()
    : null

  let error: BiString | null = null
  if (draft.grant_type === "trial" && !draft.expires) {
    error = {
      zh: "试用必须设置到期时间",
      en: "A trial requires an expiry date",
    }
  } else if (
    draft.effective &&
    draft.expires &&
    new Date(draft.expires) <= new Date(draft.effective)
  ) {
    error = {
      zh: "到期时间必须晚于开始时间",
      en: "Expiry must be later than the start time",
    }
  }

  return {
    effective_at,
    expires_at,
    grant_type: draft.grant_type,
    error,
  }
}

/* ------------------------------------------------------------------ */
/* 用量限制说明：后端 limitations 文案 → 前端双语映射                    */
/* ------------------------------------------------------------------ */

/**
 * 把后端返回的限制说明映射成前端双语文案；未识别的原样返回由组件兜底展示。
 * 匹配稳定片段（措辞调整前先改这里的分流），不直接把后端中文 detail 当界面文案。
 */
export function mapLimitation(text: string): BiString | null {
  if (text.includes("仅登录") || text.includes("登录日志")) {
    return {
      zh: "活跃口径不含仅登录用户：活跃教师为当天有教学操作的去重教师，活跃学生为当天有词汇作答的去重学生。",
      en: "Active users exclude those who only signed in: active teachers are deduplicated users with teaching actions that day; active students are deduplicated users with vocabulary answers that day.",
    }
  }
  if (text.toLowerCase().includes("farm_harvests") || text.includes("下限")) {
    return {
      zh: "农场收获为下限口径：只统计最近一次收获落在当日的地块数，不是当日真实收获次数。",
      en: "Farm harvests are a lower bound: only plots whose latest harvest falls on that day are counted, not the actual number of harvests.",
    }
  }
  return null
}
