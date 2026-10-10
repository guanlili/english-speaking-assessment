import assert from "node:assert/strict"
import test from "node:test"
import {
  blockerNotice,
  buildAttemptByItem,
  isAttemptTerminal,
  mergeItemsWithExtra,
  nextItemIdAfterCompletion,
  resolvePracticeIndex,
} from "../src/lib/practice-derive.ts"

/**
 * 练习页派生计算（批次 10-10 抽出的纯函数层）：
 * 入参取最小结构（{ id } / { item_id }），与页面传入的 PlanItem/PlanAttempt
 * 结构兼容；离开保护文案断言双语文案键逐字保留。
 */

const items = [
  { id: "i1", done: true },
  { id: "i2", done: false },
  { id: "i3", done: false },
  { id: "i4", done: true },
]

test("isAttemptTerminal：done/failed 为终态，其余（含 undefined）不是", () => {
  assert.equal(isAttemptTerminal("done"), true)
  assert.equal(isAttemptTerminal("failed"), true)
  assert.equal(isAttemptTerminal("scoring"), false)
  assert.equal(isAttemptTerminal("queued"), false)
  assert.equal(isAttemptTerminal(undefined), false)
})

test("mergeItemsWithExtra：追加新题保持计划顺序，同 id 不重复", () => {
  const plan = [{ id: "a" }, { id: "b" }]
  assert.deepEqual(
    mergeItemsWithExtra(plan, { id: "c" }).map((i) => i.id),
    ["a", "b", "c"],
  )
  // 已存在的 id 不再追加（计划刷新带回同一题时）
  assert.deepEqual(
    mergeItemsWithExtra(plan, { id: "a" }).map((i) => i.id),
    ["a", "b"],
  )
  assert.deepEqual(
    mergeItemsWithExtra(plan, null).map((i) => i.id),
    ["a", "b"],
  )
  // 不修改原数组
  assert.equal(plan.length, 2)
})

test("buildAttemptByItem：按 item_id 索引，后写覆盖前写", () => {
  const map = buildAttemptByItem([
    { item_id: "i1", status: "failed" },
    { item_id: "i2", status: "done" },
    { item_id: "i1", status: "done" },
  ])
  assert.equal(map.size, 2)
  assert.equal(map.get("i1")?.status, "done")
  assert.equal(map.get("i2")?.status, "done")
  assert.equal(map.get("i3"), undefined)
})

test("resolvePracticeIndex：钉住题 > 模考题序 > 手动聚焦 > 第一道未完成", () => {
  const isDone = (item: { id: string; done: boolean }) => item.done
  // 第一道未完成：i2（index 1）
  assert.equal(
    resolvePracticeIndex({
      items,
      focusItemId: null,
      pinnedItemId: null,
      examIndex: null,
      isItemDone: isDone,
    }),
    1,
  )
  // 手动定位优先于第一道未完成
  assert.equal(
    resolvePracticeIndex({
      items,
      focusItemId: "i3",
      pinnedItemId: null,
      examIndex: null,
      isItemDone: isDone,
    }),
    2,
  )
  // 模考服务端题序优先于手动定位；越界回夹到末题
  assert.equal(
    resolvePracticeIndex({
      items,
      focusItemId: "i3",
      pinnedItemId: null,
      examIndex: 3,
      isItemDone: isDone,
    }),
    3,
  )
  assert.equal(
    resolvePracticeIndex({
      items,
      focusItemId: null,
      pinnedItemId: null,
      examIndex: 99,
      isItemDone: isDone,
    }),
    3,
  )
  // 钉住题（提交后查看反馈）最高优先
  assert.equal(
    resolvePracticeIndex({
      items,
      focusItemId: "i3",
      pinnedItemId: "i1",
      examIndex: 3,
      isItemDone: isDone,
    }),
    0,
  )
  // 钉住/聚焦的题不在题单里（计划刷新移除）→ 回退到常规定位
  assert.equal(
    resolvePracticeIndex({
      items,
      focusItemId: "gone",
      pinnedItemId: "gone",
      examIndex: null,
      isItemDone: isDone,
    }),
    1,
  )
  // 全部完成 → 回退末题
  assert.equal(
    resolvePracticeIndex({
      items,
      focusItemId: null,
      pinnedItemId: null,
      examIndex: null,
      isItemDone: () => true,
    }),
    3,
  )
})

test("nextItemIdAfterCompletion：向后绕圈找未完成，全完成返回 null", () => {
  // 当前 i1（已完成），向后第一道未完成是 i2
  assert.equal(
    nextItemIdAfterCompletion(items, 0, (item) => item.done),
    "i2",
  )
  // 当前 i2（刚完成视作完成）：i3 未完成
  assert.equal(
    nextItemIdAfterCompletion(
      items,
      1,
      (item) => item.done || item.id === "i2",
    ),
    "i3",
  )
  // 末题之后再绕圈回头找前面的未完成（i2）
  assert.equal(
    nextItemIdAfterCompletion(items, 3, (item) => item.done),
    "i2",
  )
  // 全部完成 → null（调用方跳结果页）
  assert.equal(
    nextItemIdAfterCompletion(items, 1, () => true),
    null,
  )
})

test("blockerNotice：录音中/上传中/失败重传三态文案，双语逐字保留", () => {
  assert.equal(
    blockerNotice("recording", false, false).zh,
    "正在录音，先结束或确认录音后再离开",
  )
  assert.equal(
    blockerNotice("recording", false, false).en,
    "Recording in progress — stop or confirm the recording before leaving",
  )
  // 上传中优先于非录音的其他状态
  assert.equal(
    blockerNotice("ready", true, true).zh,
    "录音正在上传，请稍候或完成后再离开",
  )
  assert.equal(
    blockerNotice("ready", true, false).en,
    "Your recording is uploading — please wait or finish before leaving",
  )
  // 上传失败待重传：模考/普通练习文案不同
  assert.equal(
    blockerNotice("ready", false, true).zh,
    "录音上传失败，请重传原录音",
  )
  assert.equal(
    blockerNotice("ready", false, false).zh,
    "录音上传失败，请先重传或重录",
  )
  assert.equal(
    blockerNotice("ready", false, false).en,
    "Upload failed — please retry the upload or re-record first",
  )
})
