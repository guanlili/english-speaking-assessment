import assert from "node:assert/strict"
import { afterEach, beforeEach, test } from "node:test"
import { IDBFactory } from "fake-indexeddb"
import {
  clearRecordingDrafts,
  DRAFT_TTL_MS,
  deleteDraftsForItem,
  deleteRecordingDraft,
  draftKey,
  getRecordingDraft,
  listRecordingDrafts,
  MAX_DRAFTS_PER_OWNER,
  MAX_DRAFTS_TOTAL_BYTES,
  type RecordingDraftInput,
  recordingLeaveState,
  saveRecordingDraft,
  selectEvictions,
  setDraftClockForTests,
  setDraftIdbFactoryForTests,
} from "../src/lib/recording-drafts.ts"

/**
 * 录音草稿本地暂存（批次08B）：刷新后恢复待上传录音。
 * 覆盖：存取回路、跨账号隔离、登出清理、成功删草稿、配额降级与淘汰、
 * 过期清理、题目级清理。浏览器环境不可用 = "unavailable" 全降级。
 */

const NOW = 1_700_000_000_000

function freshStore(): void {
  // 每个用例独立 IDB 实例：测试之间零共享（隔离即正确性的前提）
  setDraftIdbFactoryForTests(new IDBFactory())
}

function input(
  overrides: Partial<RecordingDraftInput> = {},
): RecordingDraftInput {
  return {
    owner: "user-a",
    classroomCode: "FLOW",
    sessionId: "session-1",
    itemType: "passage",
    itemId: "item-1",
    idempotencyKey: "idem-1",
    mimeType: "audio/webm",
    durationS: 5,
    blob: new Blob(["test audio"], { type: "audio/webm" }),
    ...overrides,
  }
}

beforeEach(() => {
  freshStore()
  setDraftClockForTests(() => NOW)
})

afterEach(() => {
  setDraftIdbFactoryForTests(null)
  setDraftClockForTests(() => Date.now())
})

test("save → list/get 回路：meta 不含 Blob，get 返回 Blob", async () => {
  const result = await saveRecordingDraft(input())
  assert.equal(result, "saved")

  const metas = await listRecordingDrafts("user-a", "flow")
  assert.equal(metas.length, 1)
  assert.equal(metas[0].itemId, "item-1")
  assert.equal(metas[0].idempotencyKey, "idem-1")
  assert.equal(metas[0].size, "test audio".length)
  assert.ok(!("blob" in metas[0]))

  const record = await getRecordingDraft(metas[0].key)
  assert.ok(record)
  assert.ok(record.blob instanceof Blob)
  assert.equal(await record.blob.text(), "test audio")
  assert.equal(record.blob.type, "audio/webm")
})

test("跨账号隔离：A 的草稿对 B 不可见，B 清理不影响 A", async () => {
  await saveRecordingDraft(input({ owner: "user-a", idempotencyKey: "k1" }))
  await saveRecordingDraft(input({ owner: "user-b", idempotencyKey: "k2" }))

  assert.equal((await listRecordingDrafts("user-a", "FLOW")).length, 1)
  assert.equal((await listRecordingDrafts("user-b", "FLOW")).length, 1)

  await clearRecordingDrafts("user-b")
  assert.equal((await listRecordingDrafts("user-b", "FLOW")).length, 0)
  assert.equal((await listRecordingDrafts("user-a", "FLOW")).length, 1)
})

test("登出清理：clearRecordingDrafts 只清该账号（同设备另一账号保留）", async () => {
  await saveRecordingDraft(input({ owner: "user-a" }))
  await saveRecordingDraft(
    input({ owner: "user-b", idempotencyKey: "other-key" }),
  )
  await clearRecordingDrafts("user-a")
  const remaining = await listRecordingDrafts("user-b", "FLOW")
  assert.equal(remaining.length, 1)
})

test("成功删草稿：deleteRecordingDraft 后列表为空、get 为 null", async () => {
  await saveRecordingDraft(input())
  const [meta] = await listRecordingDrafts("user-a", "FLOW")
  await deleteRecordingDraft(meta.key)
  assert.equal((await listRecordingDrafts("user-a", "FLOW")).length, 0)
  assert.equal(await getRecordingDraft(meta.key), null)
})

test("上传接受后的题目级清理：同题不同幂等键一起清，他题保留", async () => {
  await saveRecordingDraft(input({ idempotencyKey: "k1" }))
  await saveRecordingDraft(input({ idempotencyKey: "k2", itemId: "item-1" }))
  await saveRecordingDraft(input({ idempotencyKey: "k3", itemId: "item-2" }))
  await deleteDraftsForItem("user-a", "FLOW", "session-1", "passage", "item-1")
  const metas = await listRecordingDrafts("user-a", "FLOW")
  assert.equal(metas.length, 1)
  assert.equal(metas[0].itemId, "item-2")
})

for (const [dimension, overrides] of Object.entries({
  owner: { owner: "user-b" },
  classroom: { classroomCode: "OTHER" },
  session: { sessionId: "session-2" },
  legacySession: { sessionId: null },
  itemType: { itemType: "question" as const },
  item: { itemId: "item-2" },
})) {
  test(`成功清理只限完整目标：保留不同 ${dimension} 的草稿`, async () => {
    const other = input(overrides)
    await saveRecordingDraft(input())
    await saveRecordingDraft(input({ idempotencyKey: "retry-key" }))
    await saveRecordingDraft(other)
    await deleteDraftsForItem(
      "user-a",
      "flow",
      "session-1",
      "passage",
      "item-1",
    )
    assert.equal(await getRecordingDraft(draftKey(input())), null)
    assert.equal(
      await getRecordingDraft(draftKey(input({ idempotencyKey: "retry-key" }))),
      null,
    )
    assert.ok(await getRecordingDraft(draftKey(other)))
  })
}

test("无会话目标只清 null 会话，不跨到具名会话", async () => {
  await saveRecordingDraft(input())
  const legacy = input({ sessionId: null })
  await saveRecordingDraft(legacy)
  await deleteDraftsForItem("user-a", "FLOW", null, "passage", "item-1")
  assert.equal(await getRecordingDraft(draftKey(legacy)), null)
  assert.ok(await getRecordingDraft(draftKey(input())))
})

test("上传先接受：等待同目标所有慢保存提交后再清理，且不阻塞其他会话", async () => {
  let releaseSave!: (buffer: ArrayBuffer) => void
  let startedConversion!: () => void
  const gate = new Promise<ArrayBuffer>((resolve) => {
    releaseSave = resolve
  })
  const converting = new Promise<void>((resolve) => {
    startedConversion = resolve
  })
  const slow = input()
  slow.blob.arrayBuffer = () => {
    startedConversion()
    return gate
  }
  const firstSave = saveRecordingDraft(slow)
  const secondSave = saveRecordingDraft(input({ idempotencyKey: "second" }))
  const cleanup = deleteDraftsForItem(
    "user-a",
    "flow",
    "session-1",
    "passage",
    "item-1",
  )
  await converting
  const other = input({ sessionId: "session-2" })
  assert.equal(await saveRecordingDraft(other), "saved")
  releaseSave(new TextEncoder().encode("slow audio").buffer)
  assert.deepEqual(await Promise.all([firstSave, secondSave]), [
    "saved",
    "saved",
  ])
  await cleanup
  assert.deepEqual(
    (await listRecordingDrafts("user-a", "FLOW")).map((d) => d.key),
    [draftKey(other)],
  )
  // 清理不是永久封禁：后续主动重练仍能保存同题新草稿。
  assert.equal(
    await saveRecordingDraft(input({ idempotencyKey: "later" })),
    "saved",
  )
  assert.equal((await listRecordingDrafts("user-a", "FLOW")).length, 2)
})

const cancelledRecording = {
  starting: false,
  recording: false,
  submitting: false,
  draftFlushPending: false,
  submitError: true,
  hasRecording: true,
  submissionClosed: true,
  draftSaveResult: "saved" as const,
}

test("补练撤销：草稿落盘完成后放行，存储失败或未知则须明确确认", () => {
  assert.equal(recordingLeaveState(cancelledRecording), "allowed")
  for (const draftSaveResult of ["quota", "unavailable", null] as const) {
    assert.equal(
      recordingLeaveState({ ...cancelledRecording, draftSaveResult }),
      "confirm",
    )
  }
})

test("撤销仍等待启动/录音/上传/草稿提交，不提前允许离开或丢弃", () => {
  for (const state of [
    "starting",
    "recording",
    "submitting",
    "draftFlushPending",
  ] as const) {
    for (const draftSaveResult of ["saved", "unavailable", null] as const) {
      assert.equal(
        recordingLeaveState({
          ...cancelledRecording,
          [state]: true,
          draftSaveResult,
        }),
        "blocked",
      )
    }
  }
})

test("普通断网上传失败即使已存草稿仍保护，成功或没有录音才放行", () => {
  assert.equal(
    recordingLeaveState({ ...cancelledRecording, submissionClosed: false }),
    "blocked",
  )
  assert.equal(
    recordingLeaveState({ ...cancelledRecording, submitError: false }),
    "allowed",
  )
  assert.equal(
    recordingLeaveState({ ...cancelledRecording, hasRecording: false }),
    "allowed",
  )
})

test("失败保留：删除从不自动发生（保存后无删除即仍在）", async () => {
  await saveRecordingDraft(input())
  // 模拟上传失败路径：什么都不做，草稿必须还在（e2e 覆盖 UI 行为）
  assert.equal((await listRecordingDrafts("user-a", "FLOW")).length, 1)
})

test("数量上限：第 6 条触发最旧淘汰（MAX_DRAFTS_PER_OWNER）", async () => {
  for (let i = 0; i < MAX_DRAFTS_PER_OWNER + 1; i++) {
    const result = await saveRecordingDraft(
      input({ idempotencyKey: `key-${i}` }),
    )
    assert.equal(result, "saved")
  }
  const metas = await listRecordingDrafts("user-a", "FLOW")
  assert.equal(metas.length, MAX_DRAFTS_PER_OWNER)
  // 最旧的 key-0 被淘汰，最新的 key-5 仍在
  assert.ok(!metas.some((m) => m.idempotencyKey === "key-0"))
  assert.ok(
    metas.some((m) => m.idempotencyKey === `key-${MAX_DRAFTS_PER_OWNER}`),
  )
})

test("selectEvictions：容量超限按最旧淘汰，跳过正在保存的那条", () => {
  const metas = Array.from({ length: 3 }, (_, i) => ({
    key: `k${i}`,
    owner: "u",
    classroomCode: "C",
    sessionId: null,
    itemType: "passage" as const,
    itemId: `i${i}`,
    idempotencyKey: `k${i}`,
    mimeType: "audio/webm",
    durationS: 1,
    createdAt: i,
    size: MAX_DRAFTS_TOTAL_BYTES / 2,
  }))
  // 新草稿与现存合计超限：只淘汰到刚好达标（最旧的 k0），
  // 正在保存的（skip k2）与较新的 k1 保留
  const victims = selectEvictions(metas, 1, "k2")
  assert.deepEqual(victims, ["k0"])
})

test("配额不足：清本人其余草稿重试一次，仍失败返回 quota 且不抛", async () => {
  await saveRecordingDraft(input({ idempotencyKey: "old" }))
  let calls = 0
  const putAlwaysQuota = async () => {
    calls += 1
    throw new DOMException("quota exceeded", "QuotaExceededError")
  }
  const result = await saveRecordingDraft(input({ idempotencyKey: "new" }), {
    putRecord: putAlwaysQuota,
  })
  assert.equal(result, "quota")
  assert.equal(calls, 2) // 首次 + 清理后重试各一次
  // 降级路径已尽力清掉旧草稿（重试仍失败时环境等同「存不下」）
  assert.equal((await listRecordingDrafts("user-a", "FLOW")).length, 0)
})

test("配额恢复：首次 put 配额错误、清空重试成功则 saved", async () => {
  await saveRecordingDraft(input({ idempotencyKey: "old" }))
  let firstCall = true
  const quotaOnceThenRealPut = async (
    db: IDBDatabase,
    record: { key: string },
  ) => {
    if (firstCall) {
      firstCall = false
      throw new DOMException("quota exceeded", "QuotaExceededError")
    }
    const store = db.transaction("drafts", "readwrite").objectStore("drafts")
    await new Promise<void>((resolve, reject) => {
      const req = store.put(record as never)
      req.onsuccess = () => resolve()
      req.onerror = () => reject(req.error ?? new Error("put failed"))
    })
  }
  const result = await saveRecordingDraft(input({ idempotencyKey: "new" }), {
    putRecord: quotaOnceThenRealPut,
  })
  assert.equal(result, "saved")
  const metas = await listRecordingDrafts("user-a", "FLOW")
  // 重试前清掉了旧草稿（"old"），只有重试成功写入的 "new"
  assert.equal(metas.length, 1)
  assert.equal(metas[0].idempotencyKey, "new")
})

test("过期清理：TTL 过后 list/get 自动清掉，不碰未过期草稿", async () => {
  await saveRecordingDraft(input({ idempotencyKey: "stale" }))
  setDraftClockForTests(() => NOW + DRAFT_TTL_MS + 1)
  await saveRecordingDraft(input({ idempotencyKey: "fresh" }))

  const metas = await listRecordingDrafts("user-a", "FLOW")
  assert.equal(metas.length, 1)
  assert.equal(metas[0].idempotencyKey, "fresh")

  const staleKey = draftKey({
    owner: "user-a",
    classroomCode: "FLOW",
    sessionId: "session-1",
    itemType: "passage",
    itemId: "item-1",
    idempotencyKey: "stale",
  })
  assert.equal(await getRecordingDraft(staleKey), null)
})

test("环境不可用：无 IndexedDB 时 save=unavailable、list 为空、不抛异常", async () => {
  setDraftIdbFactoryForTests(null)
  assert.equal(await saveRecordingDraft(input()), "unavailable")
  assert.deepEqual(await listRecordingDrafts("user-a", "FLOW"), [])
  assert.equal(await getRecordingDraft("any"), null)
  // 清理类操作静默成功（TTL 兜底）
  await deleteRecordingDraft("any")
  await clearRecordingDrafts("user-a")
  await deleteDraftsForItem("user-a", "FLOW", "session-1", "passage", "item-1")
})

test("draftKey：同目标同幂等键同 key，任一字段不同则不同", () => {
  const base = {
    owner: "u",
    classroomCode: "FLOW",
    sessionId: "s",
    itemType: "passage" as const,
    itemId: "i",
    idempotencyKey: "k",
  }
  assert.equal(draftKey(base), draftKey({ ...base, classroomCode: "flow" }))
  assert.notEqual(draftKey(base), draftKey({ ...base, itemId: "i2" }))
  assert.notEqual(draftKey(base), draftKey({ ...base, idempotencyKey: "k2" }))
  assert.notEqual(draftKey(base), draftKey({ ...base, owner: "u2" }))
})
