import { expect, type Page, test } from "@playwright/test"
import { EXAM_AUDIO_UNLOCK_URL } from "../../src/lib/exam-audio"

async function setup(page: Page, mockAudio = true) {
  const state = {
    index: 0,
    phase: "not_started",
    started: false,
    startedAt: 0,
    uploads: 0,
    audioEvents: 0,
    failUpload: false,
    requests: [] as string[],
  }
  const items = ["instruction", "passage", "repeat", "question"].map(
    (type, i) => ({
      id: `00000000-0000-4000-8000-00000000000${i + 1}`,
      type,
      text: `Exam prompt ${i + 1}`,
      suggested_seconds: 3,
      audio_url: type === "passage" ? null : "/audio/example.mp3",
      exam_flow: { wait_seconds: 0, after_audio_seconds: 0, prep_seconds: 0 },
    }),
  )
  await page.addInitScript((mockAudio) => {
    localStorage.setItem(
      "access_token",
      `test.${btoa(JSON.stringify({ sub: "user" }))}.test`,
    )
    localStorage.setItem("esa:role", "student")
    localStorage.setItem(
      "esa:student:EXAM",
      JSON.stringify({
        id: "student",
        display_name: "Student",
        user_id: "user",
      }),
    )
    class Recorder {
      static isTypeSupported() {
        return true
      }
      state = "inactive"
      ondataavailable: ((event: BlobEvent) => void) | null = null
      onstop: (() => void) | null = null
      interval = 0
      start() {
        this.state = "recording"
        this.interval = window.setInterval(() => this.chunk(), 250)
      }
      chunk() {
        const e = new Event("dataavailable")
        Object.defineProperty(e, "data", {
          value: new Blob(["audio"], { type: "audio/webm" }),
        })
        this.ondataavailable?.(e as BlobEvent)
      }
      stop() {
        if (this.state !== "recording") return
        this.state = "inactive"
        clearInterval(this.interval)
        this.chunk()
        queueMicrotask(() => this.onstop?.())
      }
    }
    window.MediaRecorder = Recorder as unknown as typeof MediaRecorder
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: async () => new MediaStream() },
    })
    class AudioMock {
      onended: (() => void) | null = null
      onerror: (() => void) | null = null
      onloadedmetadata: (() => void) | null = null
      currentTime = 0
      duration = 2
      timer = 0
      async play() {
        this.onloadedmetadata?.()
        this.timer = window.setTimeout(() => this.onended?.(), 1000)
      }
      pause() {
        clearTimeout(this.timer)
      }
    }
    if (mockAudio) window.Audio = AudioMock as unknown as typeof Audio
  }, mockAudio)
  function exam() {
    if (state.phase === "answering" && Date.now() - state.startedAt >= 3000)
      state.phase = "ready"
    return {
      automated: true,
      started: state.started,
      ended: false,
      phase: state.phase,
      time_limit_minutes: 5,
      remaining_seconds: 300,
      current_item_index: state.index,
      item_remaining_seconds:
        state.phase === "answering"
          ? Math.max(0, Math.ceil((3000 - Date.now() + state.startedAt) / 1000))
          : 0,
      phase_remaining_seconds: 0,
      phase_elapsed_seconds: 0,
    }
  }
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    state.requests.push(route.request().url())
    let json: unknown = []
    if (path.endsWith("/users/me"))
      json = {
        id: "user",
        role: "student",
        is_active: true,
        is_superuser: false,
      }
    if (path.endsWith("/today"))
      json = {
        session_id: "exam-session",
        classroom_code: "EXAM",
        band: "B1",
        items,
        attempts: [],
        exam: exam(),
      }
    if (path.endsWith("/exam/start")) {
      state.started = true
      state.phase = "audio"
      json = exam()
    }
    if (path.endsWith("/exam/flow")) {
      const event = route.request().postDataJSON().event
      if (event === "audio-ended") {
        state.audioEvents++
        state.phase = state.index === 0 ? "ready" : "answering"
        state.startedAt = Date.now()
      } else {
        state.index++
        state.phase =
          items[state.index]?.type === "passage" ? "answering" : "audio"
        state.startedAt = Date.now()
      }
      json = exam()
    }
    if (path.endsWith("/attempts") && route.request().method() === "POST") {
      state.uploads++
      if (state.failUpload) {
        await route.fulfill({ status: 503, json: { detail: "Unavailable" } })
        return
      }
      json = { id: `attempt-${state.uploads}`, status: "queued" }
    }
    await route.fulfill({ json })
  })
  return state
}

for (const width of [390, 820, 1180]) {
  test(`@webkit automated prompts, recording and grouped progress at ${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const state = await setup(page)
    await page.goto("/exam/EXAM")
    await page.getByRole("button", { name: "检查设备并开始考试" }).click()
    await expect(page.getByRole("button", { name: "下一题" })).toBeVisible()
    expect(state.audioEvents).toBe(1)
    const progress = page.getByRole("group", { name: "考试进度" })
    await expect(progress).not.toContainText("题目说明")
    await expect(progress).toContainText("文章朗读")
    await expect(progress).toContainText("听句复述")
    await expect(page.getByRole("button", { name: "听示范" })).toHaveCount(0)
    await expect(page.getByText("可替换句型")).toHaveCount(0)
    for (let index = 1; index < 4; index++) {
      await page.getByRole("button", { name: "下一题" }).click()
      await expect(
        page.getByText(`Exam prompt ${index + 1}`, { exact: true }),
      ).toBeVisible()
      await expect.poll(() => state.uploads, { timeout: 10000 }).toBe(index)
      await expect(page.getByRole("button", { name: "下一题" })).toBeEnabled()
    }
    await page
      .getByRole("textbox", { name: "准备笔记（不计分）" })
      .fill("My answer notes")
    await page.reload()
    await expect(
      page.getByRole("textbox", { name: "准备笔记（不计分）" }),
    ).toHaveValue("My answer notes")
    expect(
      state.requests.some((url) => url.includes("session_id=exam-session")),
    ).toBeTruthy()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy()
  })
}

test("@webkit a failed upload survives refresh and retries", async ({
  page,
}) => {
  const state = await setup(page)
  state.index = 1
  state.started = true
  state.phase = "answering"
  state.startedAt = Date.now()
  state.failUpload = true
  await page.goto("/exam/EXAM")
  await page.getByRole("button", { name: "启用声音并继续考试" }).click()
  await expect.poll(() => state.uploads).toBe(1)
  await expect(
    page.getByRole("button", { name: "恢复并提交保留的录音" }),
  ).toBeEnabled()
  await page.reload()
  await expect(
    page.getByRole("button", { name: "恢复并提交保留的录音" }),
  ).toBeEnabled()
  state.failUpload = false
  await page.getByRole("button", { name: "恢复并提交保留的录音" }).click()
  await expect.poll(() => state.uploads).toBe(2)
  await expect(page.getByRole("button", { name: "下一题" })).toBeEnabled()
})

test("@webkit the unlocked native audio element plays subsequent prompts automatically", async ({
  page,
}) => {
  const state = await setup(page, false)
  await page.route("**/audio/example.mp3", (route) =>
    route.fulfill({
      contentType: "audio/wav",
      body: Buffer.from(EXAM_AUDIO_UNLOCK_URL.split(",")[1], "base64"),
    }),
  )
  await page.goto("/exam/EXAM")
  await page.getByRole("button", { name: "检查设备并开始考试" }).click()
  await expect(page.getByRole("button", { name: "下一题" })).toBeVisible()
  expect(state.audioEvents).toBe(1)
  await page.getByRole("button", { name: "下一题" }).click()
  await expect.poll(() => state.uploads, { timeout: 10000 }).toBe(1)
  await page.getByRole("button", { name: "下一题" }).click()
  await expect.poll(() => state.audioEvents).toBe(2)
  await expect.poll(() => state.uploads, { timeout: 10000 }).toBe(2)
})
