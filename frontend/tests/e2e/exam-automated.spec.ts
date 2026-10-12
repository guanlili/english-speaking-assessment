import { expect, type Page, test } from "@playwright/test"
import { EXAM_AUDIO_UNLOCK_URL } from "../../src/lib/exam-audio"

async function setup(page: Page, mockAudio = true, lang = "zh") {
  const state = {
    index: 0,
    phase: "not_started",
    started: false,
    startedAt: 0,
    uploads: 0,
    audioEvents: 0,
    failFlow: false,
    events: [] as Array<{ session_id: string; item_id: string; event: string }>,
    failUpload: false,
    rejectUpload: false,
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
  await page.addInitScript(
    ({ mockAudio, lang }) => {
      localStorage.setItem(
        "access_token",
        `test.${btoa(JSON.stringify({ sub: "user" }))}.test`,
      )
      localStorage.setItem("esa:role", "student")
      if (lang !== "zh") localStorage.setItem("esa:lang", lang)
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
        onloadeddata: (() => void) | null = null
        src = ""
        removeAttribute() {
          this.src = ""
        }
        load() {
          if (!this.src) return
          queueMicrotask(() => {
            if ((window as unknown as { failExamAudio: boolean }).failExamAudio)
              this.onerror?.()
            else this.onloadeddata?.()
          })
        }
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
    },
    { mockAudio, lang },
  )
  function exam() {
    const limit = (items[state.index]?.suggested_seconds ?? 3) * 1000
    if (state.phase === "answering" && Date.now() - state.startedAt >= limit)
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
          ? Math.max(
              0,
              Math.ceil((limit - Date.now() + state.startedAt) / 1000),
            )
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
      const payload = route.request().postDataJSON()
      state.events.push(payload)
      if (state.failFlow) {
        await route.fulfill({ status: 503, json: { detail: "Unavailable" } })
        return
      }
      // Old events may be retried after another tab has already advanced.
      if (payload.item_id !== items[state.index]?.id) {
        await route.fulfill({ json: exam() })
        return
      }
      const event = payload.event
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
      if (state.rejectUpload) {
        await route.fulfill({
          status: 422,
          json: { detail: "音频文件无效或损坏，请重新录音" },
        })
        return
      }
      if (state.failUpload) {
        await route.fulfill({ status: 503, json: { detail: "Unavailable" } })
        return
      }
      json = { id: `attempt-${state.uploads}`, status: "queued" }
    }
    await route.fulfill({ json })
  })
  return Object.assign(state, { items })
}

for (const width of [390, 820, 1180]) {
  test(`@webkit automated prompts, recording and grouped progress at ${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const state = await setup(page)
    await page.goto("/exam/EXAM")
    await expect(
      page.getByRole("button", { name: "检查设备并开始考试" }),
    ).toBeVisible()
    // 开考前不得泄露题面：题干与笔记区都在服务端 started 之后才渲染。
    await expect(page.getByText("Exam prompt 1", { exact: true })).toHaveCount(
      0,
    )
    await expect(
      page.getByRole("textbox", { name: "准备笔记（不计分）" }),
    ).toHaveCount(0)
    await page.getByRole("button", { name: "检查设备并开始考试" }).click()
    await expect(page.getByText("Exam prompt 1", { exact: true })).toBeVisible()
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
      const prompt = page.getByText(`Exam prompt ${index + 1}`, { exact: true })
      if (
        ["instruction", "passage", "repeat", "question"][index] === "repeat"
      ) {
        // 听音复述不显示原文，只给听力提示。
        await expect(prompt).toHaveCount(0)
        await expect(page.getByText("本题不显示文字")).toBeVisible()
      } else {
        await expect(prompt).toBeVisible()
      }
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

test("@webkit instructions can be skipped before the narration finishes", async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto("/exam/EXAM")
  await page.getByRole("button", { name: "检查设备并开始考试" }).click()
  // 朗读中一键跳过：链式 audio-ended + next，直接落到下一题的作答/播放
  await page.getByRole("button", { name: "已读完 · 跳过说明" }).click()
  await expect(page.getByText("Exam prompt 2", { exact: true })).toBeVisible()
  expect(state.events.map((event) => event.event)).toEqual([
    "audio-ended",
    "next",
  ])
})

test("@webkit done speaking advances as soon as the upload lands", async ({
  page,
}) => {
  const state = await setup(page)
  state.index = 1
  state.started = true
  state.phase = "answering"
  state.startedAt = Date.now()
  // 设备启用流程可能吃掉数秒：放大本题窗口，保证按钮等待期间仍在作答中
  state.items[1].suggested_seconds = 120
  await page.goto("/exam/EXAM")
  await page.getByRole("button", { name: "启用声音并继续考试" }).click()
  // 录音满 1 秒按钮才可用（不足 1 秒的录音服务器不收）
  await expect(page.getByRole("button", { name: "我说完了" })).toBeEnabled()
  await page.getByRole("button", { name: "我说完了" }).click()
  await expect.poll(() => state.uploads).toBe(1)
  await expect
    .poll(() => state.events.filter((event) => event.event === "next").length)
    .toBe(1)
  // 下一题（repeat）自动开始播放，不再等本题倒计时走完
  await expect(page.getByText("本题不显示文字")).toBeVisible()
})

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

test("@webkit a permanently rejected upload can be discarded to continue the exam", async ({
  page,
}) => {
  const state = await setup(page)
  state.index = 1
  state.started = true
  state.phase = "answering"
  state.startedAt = Date.now()
  state.rejectUpload = true
  await page.goto("/exam/EXAM")
  await page.getByRole("button", { name: "启用声音并继续考试" }).click()
  await expect.poll(() => state.uploads).toBe(1)
  // 422 内容错误展示映射后的双语文案（不透传后端 detail），并给出确认后的放弃出口。
  await expect(page.getByText("录音文件无效或损坏，无法提交")).toBeVisible()
  await page.getByRole("button", { name: "放弃这段录音" }).click()
  await page.getByRole("button", { name: "放弃录音", exact: true }).click()
  await expect(page.getByText("录音文件无效或损坏，无法提交")).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "恢复并提交保留的录音" }),
  ).toHaveCount(0)
  await expect(page.getByRole("button", { name: "下一题" })).toBeEnabled()
})

test("@webkit an English locale maps the upload rejection to English", async ({
  page,
}) => {
  const state = await setup(page, true, "en")
  state.index = 1
  state.started = true
  state.phase = "answering"
  state.startedAt = Date.now()
  state.rejectUpload = true
  await page.goto("/exam/EXAM")
  await page
    .getByRole("button", { name: "Enable sound and resume exam" })
    .click()
  await expect.poll(() => state.uploads).toBe(1)
  await expect(
    page.getByText("The recording file is invalid or corrupted"),
  ).toBeVisible()
  await expect(page.getByText("音频文件无效或损坏")).toHaveCount(0)
})

test("@webkit exam header hides language and save-and-exit controls", async ({
  page,
}) => {
  await setup(page)
  await page.goto("/exam/EXAM")
  await expect(
    page.getByRole("heading", { name: "考试", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("group", { name: "语言 / Language" }),
  ).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: /保存并退出|Save and exit/ }),
  ).toHaveCount(0)
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

for (const lang of ["zh", "en"]) {
  test(`@webkit broken exam audio prevents starting the clock and can retry (${lang})`, async ({
    page,
  }) => {
    const state = await setup(page, true, lang)
    await page.addInitScript(() => {
      ;(window as unknown as { failExamAudio: boolean }).failExamAudio = true
    })
    await page.goto("/exam/EXAM")
    const start = page.getByRole("button", {
      name:
        lang === "zh" ? "检查设备并开始考试" : "Check devices and start exam",
    })
    await start.click()
    await expect(page.getByRole("alert")).toContainText(
      lang === "zh" ? "考试音频检查失败" : "Exam audio check failed",
    )
    expect(state.started).toBe(false)
    expect(state.requests.some((url) => url.endsWith("/exam/start"))).toBe(
      false,
    )
    expect(state.audioEvents).toBe(0)
    await page.evaluate(() => {
      ;(window as unknown as { failExamAudio: boolean }).failExamAudio = false
    })
    await start.click()
    await expect(
      page.getByRole("button", {
        name: lang === "zh" ? "下一题" : "Next",
        exact: true,
      }),
    ).toBeVisible()
    expect(state.started).toBe(true)
  })
}

test("@webkit legacy exam without TTS fails before starting, then recovers", async ({
  page,
}) => {
  const state = await setup(page)
  state.items[0].audio_url = null
  await page.addInitScript(() =>
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: undefined,
    }),
  )
  await page.goto("/exam/EXAM")
  await page.getByRole("button", { name: "检查设备并开始考试" }).click()
  await expect(page.getByRole("alert")).toContainText("考试音频检查失败")
  expect(state.started).toBe(false)
  expect(state.audioEvents).toBe(0)
  await page.evaluate(() =>
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: {
        cancel() {},
        getVoices() {
          return []
        },
        speak(utterance: SpeechSynthesisUtterance) {
          setTimeout(() => utterance.onend?.({} as SpeechSynthesisEvent), 10)
        },
      },
    }),
  )
  await page.getByRole("button", { name: "检查设备并开始考试" }).click()
  await expect(
    page.getByRole("button", { name: "下一题", exact: true }),
  ).toBeVisible()
  expect(state.started).toBe(true)
})

test("@webkit stalled legacy TTS times out before starting the exam", async ({
  page,
}) => {
  const state = await setup(page)
  state.items[0].audio_url = null
  await page.addInitScript(() =>
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: {
        cancel() {},
        getVoices() {
          return []
        },
        speak() {},
      },
    }),
  )
  await page.goto("/exam/EXAM")
  await page.clock.install()
  await page.getByRole("button", { name: "检查设备并开始考试" }).click()
  await expect(
    page.getByRole("button", { name: "正在检查设备与题目音频…" }),
  ).toBeVisible()
  await page.clock.fastForward(16_000)
  await expect(page.getByRole("alert")).toContainText("考试音频检查失败")
  expect(state.started).toBe(false)
})

test("@webkit sync retry retains the original item after another tab advances", async ({
  page,
}) => {
  const state = await setup(page)
  state.started = true
  state.phase = "ready"
  state.failFlow = true
  await page.goto("/exam/EXAM")
  await page.getByRole("button", { name: "下一题", exact: true }).click()
  await expect(page.getByRole("button", { name: "重试同步" })).toBeVisible({
    timeout: 10000,
  })
  state.index = 2
  state.phase = "audio"
  await expect(page.getByText("本题不显示文字")).toBeVisible()
  state.failFlow = false
  await page.getByRole("button", { name: "重试同步" }).click()
  await expect(page.getByRole("button", { name: "重试同步" })).toHaveCount(0)
  expect(state.events.length).toBeGreaterThanOrEqual(4)
  expect(
    state.events.every(
      (event) =>
        event.session_id === "exam-session" &&
        event.item_id === state.items[0].id &&
        event.event === "next",
    ),
  ).toBe(true)
  expect(state.index).toBe(2)
})

test("@webkit a missing real audio file blocks a new exam and recovers on retry", async ({
  page,
}) => {
  const state = await setup(page, false)
  let fail = true
  await page.route("**/audio/example.mp3", (route) =>
    fail
      ? route.fulfill({ status: 404, body: "Missing" })
      : route.fulfill({
          contentType: "audio/wav",
          body: Buffer.from(EXAM_AUDIO_UNLOCK_URL.split(",")[1], "base64"),
        }),
  )
  await page.goto("/exam/EXAM")
  const start = page.getByRole("button", { name: "检查设备并开始考试" })
  await start.click()
  await expect(page.getByRole("alert")).toContainText("考试音频检查失败")
  expect(state.started).toBe(false)
  expect(state.audioEvents).toBe(0)
  fail = false
  await start.click()
  await expect(
    page.getByRole("button", { name: "下一题", exact: true }),
  ).toBeVisible()
  expect(state.started).toBe(true)
})
