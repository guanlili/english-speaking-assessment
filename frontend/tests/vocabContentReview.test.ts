import assert from "node:assert/strict"
import test from "node:test"

import {
  CODE_DUPLICATE_WORD,
  CODE_NOT_APPROVED,
  CODE_REVIEW_STATE_CONFLICT,
  countNotApproved,
  deriveImportStats,
  isPublishableWord,
  type MorphologyPart,
  parseDetailCode,
  parseDetailCount,
  reviewStatusLabel,
  serializeMorphology,
  sourceLabel,
  validateMorphology,
} from "../src/lib/vocabContentReview.ts"

/**
 * AC4 内容治理纯逻辑：detail 编码解析、导入新增/跳过派生、发布门禁判定、
 * 词法结构校验。入参取后端最小结构；不触达 React 与网络。
 */

test("parseDetailCount：解析 `code:<n>` 计数参数", () => {
  assert.equal(
    parseDetailCount("review_state_conflict:3", CODE_REVIEW_STATE_CONFLICT),
    3,
  )
  assert.equal(
    parseDetailCount("vocabulary_words_not_approved:2", CODE_NOT_APPROVED),
    2,
  )
  // 非数字 / 非字符串 / 缺前缀 / 空参数 → null，调用方回落通用提示
  assert.equal(
    parseDetailCount("review_state_conflict:abc", CODE_REVIEW_STATE_CONFLICT),
    null,
  )
  assert.equal(parseDetailCount(null, CODE_REVIEW_STATE_CONFLICT), null)
  assert.equal(parseDetailCount("other:1", CODE_REVIEW_STATE_CONFLICT), null)
  assert.equal(
    parseDetailCount("review_state_conflict:", CODE_REVIEW_STATE_CONFLICT),
    null,
  )
})

test("parseDetailCode：提取重复键词条名（不含冒号参数的冲突码回落 null）", () => {
  assert.equal(
    parseDetailCode("vocabulary_word_duplicate:bank", CODE_DUPLICATE_WORD),
    "bank",
  )
  assert.equal(
    parseDetailCode("vocabulary_word_version_conflict", CODE_DUPLICATE_WORD),
    null,
  )
})

test("deriveImportStats：新增 = 前后词数差，跳过 = 提交数 − 新增，下限 0", () => {
  // 提交 10，词库 4 → 10：新增 6，跳过 4
  assert.deepEqual(deriveImportStats(10, 4, 10), { added: 6, skipped: 4 })
  // 新建词库 before 按 0 起算
  assert.deepEqual(deriveImportStats(5, null, 5), { added: 5, skipped: 0 })
  // 词数回退或提交为 0 时不出现负数
  assert.deepEqual(deriveImportStats(3, 10, 10), { added: 0, skipped: 3 })
  assert.deepEqual(deriveImportStats(0, 2, 2), { added: 0, skipped: 0 })
})

test("isPublishableWord：仅 approved 且未归档可发布", () => {
  assert.equal(
    isPublishableWord({ status: "active", review_status: "approved" }),
    true,
  )
  assert.equal(
    isPublishableWord({ status: "active", review_status: "pending" }),
    false,
  )
  assert.equal(
    isPublishableWord({ status: "active", review_status: "rejected" }),
    false,
  )
  assert.equal(
    isPublishableWord({ status: "archived", review_status: "approved" }),
    false,
  )
  assert.equal(isPublishableWord({}), false)
})

test("countNotApproved：汇总未通过审核（含归档）词条数", () => {
  const words = [
    { status: "active", review_status: "approved" },
    { status: "active", review_status: "pending" },
    { status: "archived", review_status: "approved" },
    { status: "active", review_status: "rejected" },
  ]
  assert.equal(countNotApproved(words), 3)
})

test("validateMorphology：空行放行；缺片段文本 / 非法类型报错", () => {
  const ok: MorphologyPart[] = [
    { text: "teach", gloss: "教", kind: "root" },
    { text: "er", gloss: "表人", kind: "suffix" },
  ]
  assert.equal(validateMorphology(ok), null)
  assert.equal(validateMorphology([]), null)

  const missingText: MorphologyPart[] = [
    { text: "", gloss: "教", kind: "root" },
  ]
  const missing = validateMorphology(missingText)
  assert.ok(missing)
  assert.match(missing.zh, /片段文本/)
  assert.match(missing.en, /text/)

  const badKind: MorphologyPart[] = [
    { text: "teach", gloss: "教", kind: "prefix-root" },
  ]
  const bad = validateMorphology(badKind)
  assert.ok(bad)
  assert.match(bad.zh, /词根|前缀|后缀/)
})

test("serializeMorphology：丢弃全空行；无有效行回传 null", () => {
  const rows: MorphologyPart[] = [
    { text: "teach", gloss: "教", kind: "root" },
    { text: "", gloss: "", kind: "" },
  ]
  assert.deepEqual(serializeMorphology(rows), [
    { text: "teach", gloss: "教", kind: "root" },
  ])
  assert.equal(serializeMorphology([]), null)
  assert.equal(
    serializeMorphology([{ text: " ", gloss: " ", kind: " " }]),
    null,
  )
})

test("双语文案：状态 / 来源有已知标签，未知值回落不抛原文", () => {
  assert.equal(reviewStatusLabel("approved").zh, "已通过")
  assert.equal(reviewStatusLabel("approved").en, "Approved")
  assert.equal(reviewStatusLabel("rejected").en, "Rejected")
  assert.equal(reviewStatusLabel(undefined).zh, "待审")
  assert.equal(reviewStatusLabel("unknown").en, "Other")

  assert.equal(sourceLabel("ai").zh, "AI")
  assert.equal(sourceLabel("import").en, "Import")
  assert.equal(sourceLabel(undefined).zh, "教师")
})
