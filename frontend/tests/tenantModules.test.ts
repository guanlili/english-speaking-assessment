import assert from "node:assert/strict"
import test from "node:test"

import { resolveBi } from "../src/lib/bi.ts"
import {
  describeBanner,
  describeModuleBadge,
  mapLimitation,
  readCompactUsage,
  usageCsvFilename,
  validateModuleForm,
  validateUsageRange,
} from "../src/lib/tenantModules.ts"

test("六态徽标：缺行按未开通", () => {
  const badge = describeModuleBadge(undefined)
  assert.equal(badge.state, "not_granted")
  assert.equal(resolveBi(badge.label, "zh"), "未开通")
  assert.equal(resolveBi(badge.label, "en"), "Not granted")
})

test("六态徽标：已关闭（即使临近/已过期也显示已关闭，由后端状态优先）", () => {
  const badge = describeModuleBadge({
    state: "disabled",
    enabled: false,
    grant_type: "paid",
    days_left: 2,
  })
  assert.equal(badge.state, "disabled")
  assert.equal(badge.tone, "muted")
  assert.equal(resolveBi(badge.label, "zh"), "已关闭")
  assert.equal(resolveBi(badge.label, "en"), "Closed")
  assert.equal(resolveBi(badge.hint, "en"), "Paid")
})

test("六态徽标：待生效", () => {
  const badge = describeModuleBadge({
    state: "scheduled",
    enabled: true,
    grant_type: "manual",
  })
  assert.equal(badge.tone, "outline")
  assert.equal(resolveBi(badge.label, "zh"), "待生效")
})

test("六态徽标：已到期为 destructive 语气", () => {
  const badge = describeModuleBadge({
    state: "expired",
    enabled: true,
    grant_type: "trial",
    days_left: 0,
  })
  assert.equal(badge.tone, "destructive")
  assert.equal(resolveBi(badge.label, "zh"), "已到期")
})

test("六态徽标：试用中显示剩余天数（中英）", () => {
  const badge = describeModuleBadge({
    state: "active",
    enabled: true,
    grant_type: "trial",
    days_left: 12,
  })
  assert.equal(resolveBi(badge.label, "zh"), "试用中 · 剩 12 天")
  assert.equal(resolveBi(badge.label, "en"), "Trial · 12 days left")
})

test("六态徽标：付费 / 人工都显示使用中，类型进 hint", () => {
  const paid = describeModuleBadge({
    state: "active",
    enabled: true,
    grant_type: "paid",
  })
  assert.equal(resolveBi(paid.label, "en"), "Active")
  assert.equal(resolveBi(paid.hint, "en"), "Paid")

  const manual = describeModuleBadge({
    state: "active",
    enabled: true,
    grant_type: "manual",
  })
  assert.equal(resolveBi(manual.hint, "zh"), "人工")
})

test("横幅阈值：试用 30 / 8 天为提示档，7 天警示，1 天紧急，31 天不提示", () => {
  const mk = (daysLeft: number) =>
    describeBanner({
      state: "active",
      enabled: true,
      grant_type: "trial",
      days_left: daysLeft,
    })
  assert.equal(mk(30).level, "trial")
  assert.equal(mk(8).level, "trial")
  assert.equal(mk(7).level, "warning")
  assert.equal(mk(1).level, "critical")
  assert.equal(mk(31).level, "none")
})

test("横幅：到期显示 expired；关闭 / 未开通 / 待生效 / 付费不提示", () => {
  assert.equal(
    describeBanner({ state: "expired", enabled: true, grant_type: "trial" })
      .level,
    "expired",
  )
  assert.equal(
    describeBanner({ state: "disabled", enabled: false }).level,
    "none",
  )
  assert.equal(describeBanner(undefined).level, "none")
  assert.equal(
    describeBanner({ state: "scheduled", enabled: true }).level,
    "none",
  )
  assert.equal(
    describeBanner({ state: "active", enabled: true, grant_type: "paid" })
      .level,
    "none",
  )
})

test("横幅优先级：enabled=false 即使试用且已过到期日也不提示", () => {
  const entry = describeBanner({
    state: "disabled",
    enabled: false,
    grant_type: "trial",
    days_left: 0,
  })
  assert.equal(entry.level, "none")
})

test("紧凑用量：五项核心指标映射，缺失补零", () => {
  const compact = readCompactUsage({
    active_teachers: 2,
    active_students: 5,
    vocab_answers: 9,
    published_tasks: 3,
    completed_students: 4,
  })
  assert.deepEqual(compact, {
    teachers: 2,
    students: 5,
    answers: 9,
    tasks: 3,
    completed: 4,
  })
  const zeros = readCompactUsage(undefined)
  assert.deepEqual(zeros, {
    teachers: 0,
    students: 0,
    answers: 0,
    tasks: 0,
    completed: 0,
  })
})

test("CSV 文件名：slug 清洗与日期拼接", () => {
  assert.equal(
    usageCsvFilename("demo-school", "2026-10-01", "2026-10-30"),
    "tenant-demo-school-usage-2026-10-01-2026-10-30.csv",
  )
  assert.equal(
    usageCsvFilename("Demo School 2", "", ""),
    "tenant-demo-school-2-usage-all-all.csv",
  )
  assert.equal(
    usageCsvFilename("", "2026-11-24", "2026-11-24"),
    "tenant-school-usage-2026-11-24-2026-11-24.csv",
  )
})

test("范围校验：合法 / 缺日期 / 倒置 / 超宽", () => {
  assert.equal(validateUsageRange("2026-11-01", "2026-11-30"), "ok")
  assert.equal(validateUsageRange("", "2026-11-30"), "missing")
  assert.equal(validateUsageRange("2026-11-30", "2026-11-01"), "invalid")
  assert.equal(validateUsageRange("2026-11-30", "not-a-date"), "invalid")
  assert.equal(validateUsageRange("2025-01-01", "2026-12-31"), "too_wide")
})

test("表单校验：trial 必填到期；到期晚于开始；付费可长期", () => {
  const trialNoExpiry = validateModuleForm({
    enabled: true,
    effective: "",
    expires: "",
    grant_type: "trial",
  })
  assert.ok(trialNoExpiry.error)
  assert.equal(resolveBi(trialNoExpiry.error!, "zh"), "试用必须设置到期时间")
  assert.equal(trialNoExpiry.expires_at, null)

  const trialOk = validateModuleForm({
    enabled: true,
    effective: "2026-11-24T10:00",
    expires: "2026-12-24T10:00",
    grant_type: "trial",
  })
  assert.equal(trialOk.error, null)
  assert.ok(trialOk.expires_at)

  const paidLongTerm = validateModuleForm({
    enabled: true,
    effective: "",
    expires: "",
    grant_type: "paid",
  })
  assert.equal(paidLongTerm.error, null)
  assert.equal(paidLongTerm.expires_at, null)

  const expiryBeforeStart = validateModuleForm({
    enabled: true,
    effective: "2026-12-24T10:00",
    expires: "2026-12-01T10:00",
    grant_type: "paid",
  })
  assert.ok(expiryBeforeStart.error)
  assert.equal(
    resolveBi(expiryBeforeStart.error!, "en"),
    "Expiry must be later than the start time",
  )
})

test("限制说明映射：登录口径 / 农场地块下限识别，未识别返回 null", () => {
  const login = mapLimitation(
    "活跃口径不含仅登录用户：当前没有登录日志或 last_login_at。",
  )
  assert.ok(login)
  assert.match(resolveBi(login, "zh"), /仅登录/)

  const farm = mapLimitation(
    "farm_harvests 为下限口径：最近一次收获落在当日的地块数。",
  )
  assert.ok(farm)

  assert.equal(mapLimitation("一条全新的未披露说明"), null)
})
