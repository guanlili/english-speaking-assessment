import assert from "node:assert/strict"
import test from "node:test"
import { practiceItemCopy } from "../src/lib/practice-copy.ts"

/**
 * 练习页题面文案（批次 10-10 抽出的纯函数层）：
 * 各题型的角标/提示分支与句序后缀，双语解析由注入的 t 决定，
 * 这里固定取中文断言（en 分支行为同构）。
 */

const zh = (bi: { zh: string }) => bi.zh

test("四种基础题型：角标与提示各归其位", () => {
  const passage = practiceItemCopy({ type: "passage", examKind: null }, zh)
  assert.equal(passage.promptLabel, "READ ALOUD · 大声朗读全文")
  assert.match(passage.hint, /先扫一眼生词/)

  const repeat = practiceItemCopy({ type: "repeat", examKind: null }, zh)
  assert.equal(repeat.promptLabel, "LISTEN & REPEAT · 听一听，再试着说")
  assert.match(repeat.hint, /先听完整句子/)

  const question = practiceItemCopy({ type: "question", examKind: null }, zh)
  assert.equal(question.promptLabel, "YOUR TURN · 分享你的想法")
  assert.match(question.hint, /试着说出你的观点/)

  const instruction = practiceItemCopy(
    { type: "instruction", examKind: null },
    zh,
  )
  assert.equal(instruction.promptLabel, "INSTRUCTIONS · 读一读再继续")
  assert.match(instruction.hint, /这一页不用录音/)
  assert.equal(instruction.isInstruction, true)
})

test("拆句逐句条目：角标带句序后缀，提示区分于整篇朗读", () => {
  const sentence = practiceItemCopy(
    {
      type: "passage",
      examKind: null,
      sentenceIndex: 2,
      sentenceTotal: 5,
    },
    zh,
  )
  assert.equal(sentence.isSentenceItem, true)
  assert.equal(sentence.promptLabel, "READ ALOUD · 逐句朗读 · 第 2/5 句")
  assert.match(sentence.hint, /把这一句读清楚/)
})

test("分级题型（exam_kind）优先于题型角标", () => {
  const ielts = practiceItemCopy({ type: "question", examKind: "ielts_p2" }, zh)
  assert.notEqual(ielts.promptLabel, "YOUR TURN · 分享你的想法")
  assert.ok(ielts.promptLabel.length > 0)
  // 未知题型码回退原样展示，不抛错
  const unknown = practiceItemCopy({ type: "repeat", examKind: "zzz" }, zh)
  assert.equal(unknown.promptLabel, "zzz")
})

test("类型判定布尔与文案语言跟随注入的 t", () => {
  const en = (bi: { en: string }) => bi.en
  const passage = practiceItemCopy({ type: "passage", examKind: null }, en)
  assert.equal(passage.promptLabel, "READ ALOUD · Read the full text aloud")
  assert.equal(passage.isPassage, true)
  assert.equal(passage.isInstruction, false)
  assert.equal(passage.isSentenceItem, false)
})
