import { expect, type Page, test } from "@playwright/test"
import type { PlanAttempt, PlanItem } from "../../src/client/types.gen"

/**
 * 学生端录音主流程（练习模式，非模考）：
 * 开始录音 → 手动停止 → 上传 → 轮询评分 → 单题反馈（转写+参考分）→
 * 下一题 → 完成后查看总反馈 → 结果页。
 * MediaRecorder / getUserMedia / 全部 API 在网络层 mock，不依赖后端。
 */

const CODE = "FLOW"

const items: PlanItem[] = [
  {
    type: "passage",
    id: "00000000-0000-4000-8000-000000000001",
    text: "Reading is to the mind what exercise is to the body.",
    suggested_seconds: 60,
  },
  {
    type: "question",
    id: "00000000-0000-4000-8000-000000000002",
    text: "What is your favorite season, and why?",
    suggested_seconds: 60,
  },
]

interface MockState {
  uploads: number
  attempts: PlanAttempt[]
  /** attempt_id → 评分终态（GET /attempts/{id} 的轮询结果） */
  scored: Map<string, PlanAttempt>
}

async function mockPractice(page: Page): Promise<MockState> {
  const state: MockState = {
    uploads: 0,
    attempts: [],
    scored: new Map(),
  }
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token")
    localStorage.setItem("esa:role", "student")
    localStorage.setItem(
      "esa:student:FLOW",
      JSON.stringify({
        id: "student",
        display_name: "Student",
        suffix: null,
        user_id: "user",
      }),
    )
    class TestRecorder {
      static isTypeSupported() {
        return true
      }
      state = "inactive"
      ondataavailable: ((event: BlobEvent) => void) | null = null
      onstart: (() => void) | null = null
      onstop: (() => void) | null = null
      start() {
        this.state = "recording"
        queueMicrotask(() => this.onstart?.())
      }
      stop() {
        if (this.state !== "recording") return
        this.state = "inactive"
        // Linux WebKit 没有全局 BlobEvent 构造器（macOS WebKit 有）：
        // 用 Event + defineProperty 造出带 data 的等价事件，两端通吃
        const dataEvent = new Event("dataavailable")
        Object.defineProperty(dataEvent, "data", {
          value: new Blob(["test audio"], { type: "audio/webm" }),
        })
        this.ondataavailable?.(dataEvent as unknown as BlobEvent)
        queueMicrotask(() => this.onstop?.())
      }
    }
    window.MediaRecorder = TestRecorder as unknown as typeof MediaRecorder
    // WebKit 的 navigator.mediaDevices 是只读属性，直接赋值静默失败：
    // 必须 defineProperty 覆盖（Chromium 宽容，两浏览器都走这条路）
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: async () => new MediaStream() },
    })
  })
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith("/users/me")) {
      body = {
        id: "user",
        role: "student",
        is_active: true,
        is_superuser: false,
      }
    } else if (path.endsWith("/today")) {
      body = {
        session_id: "flow-session",
        classroom_code: CODE,
        band: "B1",
        items,
        attempts: state.attempts,
        exam: null,
        gamification: { xp: 12, streak_days: 3 },
      }
    } else if (
      path.endsWith("/attempts") &&
      route.request().method() === "POST"
    ) {
      state.uploads += 1
      const item = items[state.uploads - 1]
      const attemptId = `attempt-${state.uploads}`
      state.attempts.push({
        item_id: item.id,
        attempt_id: attemptId,
        status: "queued",
      })
      // 预置过终态（如评分失败）则不覆盖：测试可事先决定该次作答的结局
      if (!state.scored.has(attemptId)) {
        state.scored.set(attemptId, {
          item_id: item.id,
          attempt_id: attemptId,
          status: "done",
          overall: 85,
          transcript: `Transcript for item ${state.uploads}`,
        })
      }
      body = {
        id: attemptId,
        item_type: item.type,
        item_id: item.id,
        session_id: "flow-session",
        status: "queued",
        engine: "mock",
        duration_s: 3,
      }
    } else if (path.includes("/attempts/")) {
      const attemptId = path.split("/").pop() ?? ""
      const scored = state.scored.get(attemptId)
      // 轮询到终态时同步进 today 的 attempts，模拟服务端落库
      const index = state.attempts.findIndex((a) => a.attempt_id === attemptId)
      if (scored && index >= 0) state.attempts[index] = scored
      const item = items.find((_, i) => `attempt-${i + 1}` === attemptId)
      // 终态载荷在前（status/overall/transcript 等），公共字段在后兜底
      body = {
        ...(scored ?? { status: "queued" }),
        id: attemptId,
        item_type: item?.type ?? "passage",
        item_id: item?.id ?? items[0].id,
        session_id: "flow-session",
        engine: "mock",
        duration_s: 3,
      }
    }
    await route.fulfill({ json: body })
  })
  return state
}

async function recordOneItem(page: Page) {
  await page.getByRole("button", { name: "开始录音", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "结束录音", exact: true }),
  ).toBeVisible()
  // 录音至少 1 秒（PRD：短于 1 秒不打分），再手动停止
  await page.clock.runFor(1500)
  await page.getByRole("button", { name: "结束录音", exact: true }).click()
}

test("record → upload → feedback → next item → results page", {
  tag: "@webkit",
}, async ({ page }) => {
  await page.clock.install()
  const state = await mockPractice(page)
  await page.goto(`/p/${CODE}`)

  // 第一题：录音上传后轮询到 done，出现单题反馈（转写 + 参考分）
  await expect(page.getByText(items[0].text, { exact: true })).toBeVisible()
  await recordOneItem(page)
  await page.clock.runFor(1500)
  await expect(page.getByText("你说了什么（转写）")).toBeVisible()
  await expect(page.getByText("Transcript for item 1")).toBeVisible()
  await expect(page.getByText("本次参考分 / 100")).toBeVisible()
  await expect(page.getByText("85").first()).toBeVisible()

  // 下一题：进入第二题（问答），再次录音
  await page
    .getByRole("navigation", { name: "练习选题" })
    .getByRole("button", { name: "下一题", exact: true })
    .click()
  await expect(page.getByText(items[1].text, { exact: true })).toBeVisible()
  await recordOneItem(page)
  await page.clock.runFor(1500)
  await expect(page.getByText("Transcript for item 2")).toBeVisible()

  // 全部完成：查看总反馈 → 结果页（每题转写与参考分汇总）
  await page.getByRole("button", { name: "查看详细总反馈" }).click()
  await expect(page).toHaveURL(new RegExp(`/p/${CODE}/result`))
  await expect(page.getByText("今天的你，又向前了一步。")).toBeVisible()
  expect(state.uploads).toBe(2)
})

test("failed scoring keeps practice page and allows re-recording", async ({
  page,
}) => {
  await page.clock.install()
  const state = await mockPractice(page)
  // 评分失败（status=failed）：提示再录一次，不阻塞练习
  state.scored.set("attempt-1", {
    item_id: items[0].id,
    attempt_id: "attempt-1",
    status: "failed",
  })
  await page.goto(`/p/${CODE}`)
  await expect(page.getByText(items[0].text, { exact: true })).toBeVisible()
  await recordOneItem(page)
  await page.clock.runFor(1500)
  await expect(page.getByText("这次没有评出来，再录一次就好")).toBeVisible()
  // 开始按钮重新可用：可以再录
  await expect(
    page.getByRole("button", { name: "开始录音", exact: true }),
  ).toBeEnabled()
  expect(state.uploads).toBe(1)
})

// ── 批次08B：录音草稿（刷新后恢复待上传录音）──
// 独立 mock：上传按请求里的 item_id 归属作答（原 mockPractice 按上传
// 次序选 item，重传场景会错位）；token 是结构合法的 JWT（sub=user），
// 草稿属主才能从 payload 解析出来。

const DRAFT_TOKEN = `e30.${Buffer.from(
  JSON.stringify({ sub: "user", role: "student" }),
).toString("base64url")}.sig`

const draftItems = [
  {
    type: "passage",
    id: "00000000-0000-4000-8000-0000000000a1",
    text: "Draft recovery passage text.",
    suggested_seconds: 60,
  },
  {
    type: "question",
    id: "00000000-0000-4000-8000-0000000000a2",
    text: "Draft recovery question text?",
    suggested_seconds: 60,
  },
] as PlanItem[]

interface DraftMockState {
  /** 上传结果可控，撤销与普通网络故障分别回归。 */
  uploadOutcome: "ok" | "fail" | "offline" | "reject" | "cancelled"
  uploadRequests: string[]
  uploadGate?: Promise<void>
  /** today 计划的题目（可换成"老师重新发布"后的内容） */
  planItems: typeof draftItems
  uploads: number
  attempts: PlanAttempt[]
}

async function mockDraftPractice(page: Page): Promise<DraftMockState> {
  const state: DraftMockState = {
    uploadOutcome: "ok",
    uploadRequests: [],
    planItems: [draftItems[0], draftItems[1]],
    uploads: 0,
    attempts: [],
  }
  await page.addInitScript((token: string) => {
    localStorage.setItem("access_token", token)
    localStorage.setItem("esa:role", "student")
    localStorage.setItem(
      "esa:student:DRAFT",
      JSON.stringify({
        id: "student",
        display_name: "Student",
        suffix: null,
        user_id: "user",
      }),
    )
    class TestRecorder {
      static isTypeSupported() {
        return true
      }
      state = "inactive"
      ondataavailable: ((event: BlobEvent) => void) | null = null
      onstart: (() => void) | null = null
      onstop: (() => void) | null = null
      start() {
        this.state = "recording"
        queueMicrotask(() => this.onstart?.())
      }
      stop() {
        if (this.state !== "recording") return
        this.state = "inactive"
        // Linux WebKit 无全局 BlobEvent：Event + defineProperty 等价实现
        const dataEvent = new Event("dataavailable")
        Object.defineProperty(dataEvent, "data", {
          value: new Blob(["draft test audio"], { type: "audio/webm" }),
        })
        this.ondataavailable?.(dataEvent as unknown as BlobEvent)
        queueMicrotask(() => this.onstop?.())
      }
    }
    window.MediaRecorder = TestRecorder as unknown as typeof MediaRecorder
    // WebKit 的 navigator.mediaDevices 是只读属性，直接赋值静默失败：
    // 必须 defineProperty 覆盖（Chromium 宽容，两浏览器都走这条路）
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: async () => new MediaStream() },
    })
  }, DRAFT_TOKEN)
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith("/users/me")) {
      body = {
        id: "user",
        role: "student",
        is_active: true,
        is_superuser: false,
      }
    } else if (path.endsWith("/today")) {
      body = {
        session_id: "draft-session",
        classroom_code: "DRAFT",
        band: "B1",
        items: state.planItems,
        attempts: state.attempts,
        exam: null,
        gamification: { xp: 0, streak_days: 0 },
      }
    } else if (
      path.endsWith("/attempts") &&
      route.request().method() === "POST"
    ) {
      state.uploadRequests.push(
        route.request().postDataBuffer()?.toString("latin1") ?? "",
      )
      await state.uploadGate
      if (state.uploadOutcome === "offline") {
        await route.abort("internetdisconnected")
        return
      }
      if (state.uploadOutcome === "cancelled") {
        await route.fulfill({
          status: 403,
          json: { detail: "Followup cancelled" },
        })
        return
      }
      if (state.uploadOutcome === "fail") {
        await route.fulfill({ status: 500, json: { detail: "boom" } })
        return
      }
      if (state.uploadOutcome === "reject") {
        await route.fulfill({
          status: 422,
          json: { detail: "Exam item window closed" },
        })
        return
      }
      // multipart 原始体里抽 item_id（UUID 为 ASCII，latin1 解码安全）
      const raw = route.request().postDataBuffer()?.toString("latin1") ?? ""
      const itemId = /name="item_id"\r\n\r\n([^\r]+)\r\n/.exec(raw)?.[1] ?? ""
      state.uploads += 1
      const attemptId = `draft-attempt-${itemId}`
      if (!state.attempts.some((a) => a.item_id === itemId)) {
        state.attempts.push({
          item_id: itemId,
          attempt_id: attemptId,
          status: "queued",
        })
      }
      body = {
        id: attemptId,
        item_type: "passage",
        item_id: itemId,
        session_id: "draft-session",
        status: "queued",
        engine: "mock",
        duration_s: 3,
      }
    } else if (path.includes("/attempts/")) {
      const attemptId = path.split("/").pop() ?? ""
      const attempt = state.attempts.find((a) => a.attempt_id === attemptId)
      // 模拟评分落库：GET 即视为终态 done（页面上传成功后删除草稿）
      if (attempt) attempt.status = "done"
      body = {
        ...(attempt ?? { status: "done" }),
        id: attemptId,
        item_type: "passage",
        item_id: attempt?.item_id ?? draftItems[0].id,
        session_id: "draft-session",
        engine: "mock",
        duration_s: 3,
        overall: 80,
        transcript: "Draft transcript",
      }
    }
    await route.fulfill({ json: body })
  })
  return state
}

async function recordOneDraftItem(page: Page) {
  await page
    .getByRole("button", { name: /^(开始录音|Start recording)$/ })
    .click()
  await expect(
    page.getByRole("button", { name: /^(结束录音|Stop recording)$/ }),
  ).toBeVisible()
  await page.clock.runFor(1500)
  await page
    .getByRole("button", { name: /^(结束录音|Stop recording)$/ })
    .click()
}

interface DraftStorageControl {
  conversionStarted: boolean
  releaseSave: () => void
}

async function holdDraftSave(page: Page, fail: "quota" | null = null) {
  await page.addInitScript((fail) => {
    let releaseSave!: () => void
    const gate = new Promise<void>((resolve) => {
      releaseSave = resolve
    })
    const control: DraftStorageControl = {
      conversionStarted: false,
      releaseSave,
    }
    Object.assign(window, { draftStorageControl: control })
    const arrayBuffer = Blob.prototype.arrayBuffer
    Blob.prototype.arrayBuffer = async function () {
      if (this.type.startsWith("audio/")) {
        control.conversionStarted = true
        await gate
      }
      return arrayBuffer.call(this)
    }
    if (fail) {
      const put = IDBObjectStore.prototype.put
      IDBObjectStore.prototype.put = function (...args) {
        if (this.name === "drafts")
          throw new DOMException("Full", "QuotaExceededError")
        return put.apply(this, args)
      }
    }
  }, fail)
}

async function releaseDraftSave(page: Page) {
  await page.evaluate(() => {
    ;(
      window as unknown as { draftStorageControl: DraftStorageControl }
    ).draftStorageControl.releaseSave()
  })
}

async function beforeUnloadBlocked(page: Page) {
  return page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true })
    window.dispatchEvent(event)
    return event.defaultPrevented
  })
}

async function storedDrafts(page: Page) {
  return page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open("esa-recording-drafts", 1)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    try {
      return await new Promise<
        Array<{
          key: string
          sessionId: string | null
          itemType: string
          idempotencyKey: string
        }>
      >((resolve, reject) => {
        const request = db
          .transaction("drafts", "readonly")
          .objectStore("drafts")
          .getAll()
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => reject(request.error)
      })
    } finally {
      db.close()
    }
  })
}

test("@webkit accepted upload waits for draft writes and only cleans the complete target", async ({
  page,
}) => {
  await page.clock.install()
  const state = await mockDraftPractice(page)
  await holdDraftSave(page)
  await page.goto("/p/DRAFT")
  await expect(page.getByText(draftItems[0].text)).toBeVisible()
  await page.evaluate(async (itemId) => {
    const request = indexedDB.open("esa-recording-drafts", 1)
    const db = await new Promise<IDBDatabase>((resolve) => {
      request.onsuccess = () => resolve(request.result)
    })
    const tx = db.transaction("drafts", "readwrite")
    for (const [sessionId, itemType, idempotencyKey] of [
      ["draft-session", "passage", "old-key"],
      ["other-session", "passage", "other-session-key"],
      [null, "passage", "legacy-key"],
      ["draft-session", "question", "other-type-key"],
    ]) {
      tx.objectStore("drafts").put({
        key: [
          "user",
          "DRAFT",
          sessionId ?? "",
          itemType,
          itemId,
          idempotencyKey,
        ].join("|"),
        owner: "user",
        classroomCode: "DRAFT",
        sessionId,
        itemType,
        itemId,
        idempotencyKey,
        mimeType: "audio/webm",
        durationS: 2,
        createdAt: Date.now(),
        blob: new TextEncoder().encode("old audio").buffer,
      })
    }
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve()
      tx.onabort = () => reject(tx.error)
    })
    db.close()
  }, draftItems[0].id)

  await recordOneDraftItem(page)
  await expect.poll(() => state.uploads).toBe(1)
  await expect(page.getByText("Draft transcript")).toBeVisible()
  await page.waitForFunction(
    () =>
      (window as unknown as { draftStorageControl: DraftStorageControl })
        .draftStorageControl.conversionStarted,
  )
  // 已收到服务器成功，但 Blob 转换仍挂起；旧同目标草稿也不能提前清理。
  expect(
    (await storedDrafts(page)).some((d) => d.idempotencyKey === "old-key"),
  ).toBe(true)
  expect(await beforeUnloadBlocked(page)).toBe(true)
  await releaseDraftSave(page)
  await expect
    .poll(async () =>
      (await storedDrafts(page)).map((d) => d.idempotencyKey).sort(),
    )
    .toEqual(["legacy-key", "other-session-key", "other-type-key"])
  await expect.poll(() => beforeUnloadBlocked(page)).toBe(false)
  await page.reload()
  const drafts = await storedDrafts(page)
  expect(drafts).toHaveLength(3)
  expect(
    drafts.some(
      (d) => d.sessionId === "draft-session" && d.itemType === "passage",
    ),
  ).toBe(false)
})

test("@webkit withdrawn followup blocks until its draft is saved, then permits leaving", async ({
  page,
}) => {
  await page.clock.install()
  const state = await mockDraftPractice(page)
  state.uploadOutcome = "cancelled"
  await holdDraftSave(page)
  await page.goto("/p/DRAFT?session=draft-session")
  await recordOneDraftItem(page)
  const home = page.getByRole("button", { name: "返回首页", exact: true })
  await expect(
    page.getByText("正在保存录音草稿，请稍候再离开。", { exact: true }),
  ).toBeVisible()
  await expect(home).toBeDisabled()
  await expect(page.getByRole("button", { name: "重传录音" })).toBeHidden()
  await expect(
    page.getByRole("button", { name: "开始录音", exact: true }),
  ).toBeHidden()
  expect(await beforeUnloadBlocked(page)).toBe(true)
  await page
    .getByRole("link", { name: "学习首页", exact: true })
    .first()
    .click()
  await expect(page).toHaveURL(/\/p\/DRAFT/)
  await releaseDraftSave(page)
  await expect(home).toBeEnabled()
  await expect(
    page.getByText(
      "录音草稿已保存在本设备，但不能再提交到这项补练。现在可以返回首页。",
      { exact: true },
    ),
  ).toBeVisible()
  expect(await storedDrafts(page)).toHaveLength(1)
  expect(await beforeUnloadBlocked(page)).toBe(false)
  await home.click()
  await expect(page).toHaveURL(/\/home\/DRAFT/)
  expect(await storedDrafts(page)).toHaveLength(1)
  expect(state.uploadRequests).toHaveLength(1)
})

for (const [width, lang, failure] of [
  [390, "zh", "unavailable"],
  [820, "en", "quota"],
  [1180, "zh", "quota"],
] as const) {
  test(`@webkit withdrawn followup confirms unsaved recording loss at ${width} ${lang} ${failure}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.clock.install()
    const state = await mockDraftPractice(page)
    state.uploadOutcome = "cancelled"
    await page.addInitScript(
      (lang) => localStorage.setItem("esa:lang", lang),
      lang,
    )
    if (failure === "quota") await holdDraftSave(page, "quota")
    else
      await page.addInitScript(() => {
        IDBFactory.prototype.open = () => {
          throw new DOMException("Denied", "SecurityError")
        }
      })
    await page.goto("/p/DRAFT?session=draft-session")
    await recordOneDraftItem(page)
    const home = page.getByRole("button", { name: /^(返回首页|Return home)$/ })
    if (failure === "quota") {
      await expect(home).toBeDisabled()
      await releaseDraftSave(page)
    }
    await expect(home).toBeEnabled()
    await expect(
      page.getByText(
        lang === "en"
          ? "This recording was neither uploaded nor saved on this device. Leaving will lose it; confirmation is required before returning home."
          : "这段录音未上传，也未能保存到本设备。离开将丢失录音；返回首页前需要确认。",
        { exact: true },
      ),
    ).toBeVisible()
    expect(await beforeUnloadBlocked(page)).toBe(true)
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true)
    const box = await home.boundingBox()
    expect(box?.height).toBeGreaterThanOrEqual(44)

    const dismissed = page.waitForEvent("dialog")
    void home.click()
    const first = await dismissed
    expect(first.type()).toBe("confirm")
    expect(first.message()).toContain(
      lang === "en" ? "Leaving will lose it" : "离开将丢失这段录音",
    )
    await first.dismiss()
    await expect(page).toHaveURL(/\/p\/DRAFT/)
    expect(await beforeUnloadBlocked(page)).toBe(true)
    // 取消确认不释放保护；第二次从站内侧栏离开仍须确认。
    const confirmed = page.waitForEvent("dialog")
    void page
      .getByRole("link", { name: /^(学习首页|Home)$/ })
      .first()
      .click()
    const second = await confirmed
    expect(second.type()).toBe("confirm")
    await second.accept()
    await expect(page).toHaveURL(/\/home\/DRAFT/)
    expect(state.uploadRequests).toHaveLength(1)
  })
}

test("@webkit ordinary recording, uploading and network failure retain leave protection and retry key", async ({
  page,
}) => {
  await page.clock.install()
  const state = await mockDraftPractice(page)
  state.uploadOutcome = "offline"
  let releaseUpload!: () => void
  state.uploadGate = new Promise<void>((resolve) => {
    releaseUpload = resolve
  })
  await page.goto("/p/DRAFT")
  await page.getByRole("button", { name: "开始录音", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "结束录音", exact: true }),
  ).toBeVisible()
  const home = page.getByRole("link", { name: "学习首页", exact: true }).first()
  await home.click()
  await expect(page).toHaveURL(/\/p\/DRAFT/)
  expect(await beforeUnloadBlocked(page)).toBe(true)
  await page.clock.runFor(1500)
  await page.getByRole("button", { name: "结束录音", exact: true }).click()
  await expect.poll(() => state.uploadRequests.length).toBe(1)
  await home.click()
  await expect(page).toHaveURL(/\/p\/DRAFT/)
  expect(await beforeUnloadBlocked(page)).toBe(true)
  releaseUpload()
  await expect(page.getByText("上传失败，录音已保留")).toBeVisible()
  await expect.poll(async () => (await storedDrafts(page)).length).toBe(1)
  await home.click()
  await expect(page).toHaveURL(/\/p\/DRAFT/)
  expect(await beforeUnloadBlocked(page)).toBe(true)
  await expect(
    page.getByRole("button", { name: "重新录", exact: true }),
  ).toBeVisible()
  state.uploadOutcome = "ok"
  await page.getByRole("button", { name: "重传录音" }).click()
  await expect(page.getByText("Draft transcript")).toBeVisible()
  await expect.poll(async () => (await storedDrafts(page)).length).toBe(0)
  expect(state.uploadRequests).toHaveLength(2)
  const key = (raw: string) =>
    /name="idempotency_key"\r\n\r\n([^\r]+)\r\n/.exec(raw)?.[1]
  expect(key(state.uploadRequests[0])).toBeTruthy()
  expect(key(state.uploadRequests[1])).toBe(key(state.uploadRequests[0]))
  await home.click()
  await expect(page).toHaveURL(/\/home\/DRAFT/)
})

test("draft survives reload after failed upload and can be re-uploaded", {
  tag: "@webkit",
}, async ({ page }) => {
  // 草稿使用 ArrayBuffer 落盘，Chromium 与 WebKit 都验证真实 IndexedDB。
  await page.clock.install()
  const state = await mockDraftPractice(page)
  state.uploadOutcome = "fail"

  await page.goto("/p/DRAFT")
  await expect(page.getByText(draftItems[0].text)).toBeVisible()
  // 录完即落草稿；上传 500 失败（内存重传可用，草稿兜底）
  await recordOneDraftItem(page)
  // RecordArea 的稳定错误文案（toast「上传失败」与它同名，避免 strict 冲突）
  await expect(page.getByText("上传失败，录音已保留")).toBeVisible()
  // 等草稿落盘完成（IndexedDB 异步写）
  await expect.poll(async () => (await storedDrafts(page)).length).toBe(1)

  // 刷新：内存里的录音没了，只剩草稿——恢复卡出现且明确列出原题
  // （题文在题面与卡片各出现一次，断言限定在卡片区域内）
  await page.reload()
  const card = page.getByRole("region", { name: "未上传的录音草稿" })
  await expect(card).toBeVisible()
  await expect(card.getByText(draftItems[0].text)).toBeVisible()

  // 恢复上传：网络恢复后一次成功，草稿删除、卡片消失、反馈出现
  state.uploadOutcome = "ok"
  await page.getByRole("button", { name: "上传这段录音" }).click()
  await expect(page.getByText("有未上传的录音草稿")).toBeHidden()
  await page.clock.runFor(2500)
  await expect(page.getByText("Draft transcript")).toBeVisible()
  expect(state.uploads).toBe(1)
})

test("server-rejected draft stays with server-authoritative message", {
  tag: "@webkit",
}, async ({ page }) => {
  // 草稿使用 ArrayBuffer 落盘，Chromium 与 WebKit 都验证真实 IndexedDB。
  await page.clock.install()
  const state = await mockDraftPractice(page)
  state.uploadOutcome = "fail"

  await page.goto("/p/DRAFT")
  await recordOneDraftItem(page)
  await expect.poll(async () => (await storedDrafts(page)).length).toBe(1)
  await page.reload()
  await expect(page.getByText("有未上传的录音草稿")).toBeVisible()

  // 服务器拒绝（模拟考试截止/题窗关闭）：结果以服务器为准，草稿保留不自动重试
  state.uploadOutcome = "reject"
  await page.getByRole("button", { name: "上传这段录音" }).click()
  await expect(
    page.getByText("服务器没有接受这段录音", { exact: false }),
  ).toBeVisible()
  await expect(page.getByText("有未上传的录音草稿")).toBeVisible()

  // 丢弃需两步确认；丢弃后卡片消失
  await page.getByRole("button", { name: "丢弃", exact: true }).click()
  await page.getByRole("button", { name: "确认丢弃" }).click()
  await expect(page.getByText("有未上传的录音草稿")).toBeHidden()
})

test("draft for republished plan item offers discard only", {
  tag: "@webkit",
}, async ({ page }) => {
  // 草稿使用 ArrayBuffer 落盘，Chromium 与 WebKit 都验证真实 IndexedDB。
  await page.clock.install()
  const state = await mockDraftPractice(page)
  state.uploadOutcome = "fail"

  await page.goto("/p/DRAFT")
  await recordOneDraftItem(page)
  await expect.poll(async () => (await storedDrafts(page)).length).toBe(1)

  // 老师重新发布计划：草稿的题不在新计划里——不能上传（目标已失效），只能丢弃
  state.planItems = [draftItems[1]]
  await page.reload()
  await expect(page.getByText("有未上传的录音草稿")).toBeVisible()
  await expect(
    page.getByText("本题已不在今天的练习中", { exact: false }),
  ).toBeVisible()
  await expect(page.getByRole("button", { name: "上传这段录音" })).toBeHidden()
  await page.getByRole("button", { name: "丢弃", exact: true }).click()
  await page.getByRole("button", { name: "确认丢弃" }).click()
  await expect(page.getByText("有未上传的录音草稿")).toBeHidden()
})
