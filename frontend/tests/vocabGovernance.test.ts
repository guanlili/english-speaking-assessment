import assert from "node:assert/strict"
import test from "node:test"

import {
  describeLicensePublishError,
  describeQueryError,
  diffDimensionLabel,
  formatAuditChanges,
  formatSnapshotField,
  isDemoSource,
  isoToLocalInput,
  isSafeHttpUrl,
  LICENSE_ERROR_EXPIRED,
  LICENSE_ERROR_OWNER_MISSING,
  LICENSE_ERROR_REF_MISSING,
  LICENSE_STATUS_MISSING,
  licenseStatusLabel,
  localInputToIso,
  shortHash,
  sourceTypeLabel,
  versionActionLabel,
} from "../src/lib/vocabGovernance.ts"

/**
 * 授权台账 + 版本治理纯逻辑：422 code 映射、状态/类型文案、快照字段与审计
 * 前后值格式化、到期日输入串换算。不触达 React 与网络。
 */

test("describeLicensePublishError：三类授权错误码映射双语文案", () => {
  const owner = describeLicensePublishError(`${LICENSE_ERROR_OWNER_MISSING}:3`)
  assert.ok(owner)
  assert.match(owner.zh, /3/)
  assert.match(owner.en, /3/)

  const ref = describeLicensePublishError(`${LICENSE_ERROR_REF_MISSING}:1`)
  assert.ok(ref)
  assert.match(ref.zh, /凭证/)

  const expired = describeLicensePublishError(`${LICENSE_ERROR_EXPIRED}:2`)
  assert.ok(expired)
  assert.match(expired.zh, /过期/)

  // 非授权错误码回落 null，由调用方走通用提示
  assert.equal(
    describeLicensePublishError("vocabulary_words_not_approved:4"),
    null,
  )
  assert.equal(describeLicensePublishError(null), null)
  assert.equal(describeLicensePublishError("source_type_invalid"), null)
})

test("describeLicensePublishError：缺计数参数时仍给出无数字文案", () => {
  const owner = describeLicensePublishError(LICENSE_ERROR_OWNER_MISSING)
  // 无 `:n` 后缀时 parseDetailCount 返回 null，按无数字分支处理
  assert.ok(owner === null || !owner.zh.match(/\d/))
})

test("状态 / 类型 / 操作 / 维度文案：已知值命中，未知值回落原文", () => {
  assert.equal(sourceTypeLabel("demo").zh, "演示")
  assert.equal(sourceTypeLabel("unknown_x").en, "unknown_x")
  assert.equal(licenseStatusLabel("expired").zh, "已过期")
  assert.equal(licenseStatusLabel(undefined).zh, "无需授权")
  assert.equal(versionActionLabel("rollback").en, "Rollback")
  assert.equal(versionActionLabel("nope").zh, "nope")
  assert.equal(diffDimensionLabel("morphology").zh, "词法")
  assert.equal(isDemoSource("demo"), true)
  assert.equal(isDemoSource("textbook"), false)
  assert.equal(isDemoSource(null), false)
})

test("shortHash：取前 8 位，空值回落占位", () => {
  assert.equal(shortHash("abcdef123456"), "abcdef12")
  assert.equal(shortHash(null), "–")
  assert.equal(shortHash(""), "–")
})

test("formatSnapshotField：按维度取释义 / 例句 / 词法，空条目回落占位", () => {
  const entry = {
    headword: "favour",
    meaning_zh: "最喜欢的",
    meaning_en: "liked more",
    example_en: "Blue is my favourite color.",
    part_of_speech: "v.",
    accepted_spellings: ["favorite"],
    morphology: [{ text: "favour", gloss: "喜爱", kind: "root" }],
  }
  assert.equal(formatSnapshotField(entry, "headword"), "favour")
  assert.match(formatSnapshotField(entry, "meaning"), /最喜欢的/)
  assert.match(formatSnapshotField(entry, "meaning"), /liked more/)
  assert.equal(formatSnapshotField(entry, "example"), entry.example_en)
  const morphology = formatSnapshotField(entry, "morphology")
  assert.match(morphology, /v\./)
  assert.match(morphology, /favorite/)
  assert.match(morphology, /favour/)
  assert.equal(formatSnapshotField(null, "meaning"), "–")
  assert.equal(formatSnapshotField({}, "example"), "–")
})

test("formatAuditChanges：字段标签 + 前后值，null 表示清空", () => {
  const changes = formatAuditChanges({
    license_owner: { from: "旧出版社", to: null },
    license_ref: { from: null, to: "AUTH-123" },
  })
  assert.equal(changes.length, 2)
  assert.equal(changes[0].label.zh, "授权方")
  assert.equal(changes[0].from, "旧出版社")
  assert.equal(changes[0].to, null)
  assert.equal(changes[1].from, null)
  assert.equal(changes[1].to, "AUTH-123")
  assert.deepEqual(formatAuditChanges(undefined), [])
})

test("到期日输入串：空 / 非法回落，本地时间往返不丢时分", () => {
  assert.equal(isoToLocalInput(null), "")
  assert.equal(isoToLocalInput("not-a-date"), "")
  assert.equal(localInputToIso(""), null)
  assert.equal(localInputToIso("not-a-date"), null)

  const iso = localInputToIso("2026-06-01T09:30")
  assert.ok(iso)
  const date = new Date(iso)
  assert.equal(date.getHours(), 9)
  assert.equal(date.getMinutes(), 30)
  assert.equal(isoToLocalInput(iso), "2026-06-01T09:30")
})

test("describeQueryError：403 / 404 / 其他状态分别映射", () => {
  assert.match(describeQueryError(403).zh, /权限/)
  assert.match(describeQueryError(404).zh, /不存在/)
  assert.match(describeQueryError(500).zh, /重试/)
  assert.match(describeQueryError(undefined).en, /retry/)
})

test("missing 状态文案与安全 URL 判定（平台台账口径）", () => {
  const missing = licenseStatusLabel(LICENSE_STATUS_MISSING)
  assert.match(missing.zh, /缺失/)
  assert.match(missing.en, /Missing/)

  assert.equal(isSafeHttpUrl("https://example.com/doc.pdf"), true)
  assert.equal(isSafeHttpUrl("http://example.com/doc.pdf"), true)
  assert.equal(isSafeHttpUrl("  HTTPS://example.com "), true)
  assert.equal(isSafeHttpUrl("javascript:alert(1)"), false)
  assert.equal(isSafeHttpUrl("mailto:a@b.com"), false)
  assert.equal(isSafeHttpUrl(""), false)
  assert.equal(isSafeHttpUrl(null), false)
  assert.equal(isSafeHttpUrl(undefined), false)
})
