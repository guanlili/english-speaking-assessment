import { expect, type Page, test } from "@playwright/test"
import type { PlanAttempt } from "../../src/client/types.gen"

const items = [0, 1].map((index) => ({
  id: `00000000-0000-4000-8000-00000000000${index + 1}`,
  type: "repeat",
  text: `Timed article ${index + 1}.`,
  suggested_seconds: 30,
  replay_limit: 1,
  listen_used: 1,
}))

async function mockExam(page: Page, isExam = true, nextType = "repeat") {
  const state = {
    index: 0,
    ended: false,
    attempts: [] as PlanAttempt[],
    uploads: 0,
    submittedItems: [] as string[],
    failUpload: false,
    prepSeconds: 0,
  }
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token")
    localStorage.setItem("esa:role", "student")
    localStorage.setItem(
      "esa:student:EXAM",
      JSON.stringify({
        id: "student",
        display_name: "Student",
        suffix: null,
        user_id: "user",
      }),
    )
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: {
        cancel() {},
        getVoices() {
          return []
        },
        speak(utterance: SpeechSynthesisUtterance) {
          setTimeout(
            () => utterance.onend?.(new Event("end") as SpeechSynthesisEvent),
            10,
          )
        },
      },
    })
    class TestRecorder {
      static isTypeSupported() {
        return true
      }
      state = "inactive"
      ondataavailable: ((event: BlobEvent) => void) | null = null
      onstop: (() => void) | null = null
      start() {
        this.state = "recording"
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
    if (path.endsWith("/users/me"))
      body = {
        id: "user",
        role: "student",
        is_active: true,
        is_superuser: false,
      }
    else if (path.endsWith("/today"))
      body = {
        session_id: "exam-session",
        classroom_code: "EXAM",
        band: "B1",
        items:
          state.prepSeconds > 0
            ? items.map((item, index) =>
                index === 0
                  ? {
                      ...item,
                      type: "question",
                      exam_kind: "ielts_p2",
                      prep_seconds: state.prepSeconds,
                      cue_card_bullets: ["Describe the place"],
                    }
                  : item,
              )
            : items.map((item, index) =>
                index === 1 ? { ...item, type: nextType } : item,
              ),
        attempts: state.attempts,
        exam: isExam
          ? {
              started: true,
              ended: state.ended,
              time_limit_minutes: 30,
              remaining_seconds: 1800,
              current_item_index: state.index,
              item_remaining_seconds: 3 + state.prepSeconds,
              prep_remaining_seconds: state.prepSeconds,
            }
          : null,
      }
    else if (
      path.endsWith("/attempts") &&
      route.request().method() === "POST"
    ) {
      if (state.failUpload) {
        await route.fulfill({
          status: 503,
          json: { detail: "评分队列繁忙，请稍后重传" },
        })
        return
      }
      const item =
        items.find((candidate) =>
          route.request().postData()?.includes(candidate.id),
        ) ?? items[state.index]
      state.submittedItems.push(item.id)
      state.attempts.push({
        item_id: item.id,
        attempt_id: `attempt-${state.index}`,
        status: "queued",
      })
      state.uploads += 1
      state.index += 1
      state.ended = state.index >= items.length
      body = {
        id: `attempt-${state.index - 1}`,
        item_type: "repeat",
        item_id: item.id,
        session_id: "exam-session",
        status: "queued",
        engine: "mock",
        duration_s: 3,
      }
    } else if (path.includes("/attempts/"))
      body = {
        id: "attempt-0",
        item_type: "repeat",
        item_id: items[0].id,
        status: "queued",
        engine: "mock",
        duration_s: 3,
      }
    await route.fulfill({ json: body })
  })
  return state
}

for (const width of [390, 820, 1180]) {
  test(`@webkit practice freely selects and swipes at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    await mockExam(page, false)
    await page.goto("/p/EXAM")
    const picker = page.getByRole("combobox", { name: "选择练习题" })
    await expect(picker).toHaveValue(items[0].id)
    await page.getByRole("button", { name: "下一题", exact: true }).click()
    await expect(picker).toHaveValue(items[1].id)
    await picker.selectOption(items[0].id)
    const prompt = page.getByText(
      "本题不显示文字。点下方「听示范」听语音，听完后复述出来。",
      { exact: true },
    )
    await expect(prompt).toBeVisible()
    await prompt.dispatchEvent("touchstart", {
      touches: [{ identifier: 1, clientX: 300, clientY: 300 }],
    })
    await prompt.dispatchEvent("touchend", {
      changedTouches: [{ identifier: 1, clientX: 100, clientY: 310 }],
    })
    await expect(picker).toHaveValue(items[1].id)
    await page.getByRole("button", { name: "上一题", exact: true }).click()
    await expect(picker).toHaveValue(items[0].id)
    await prompt.dispatchEvent("touchstart", {
      touches: [{ identifier: 1, clientX: 300, clientY: 300 }],
    })
    await prompt.dispatchEvent("touchend", {
      changedTouches: [{ identifier: 1, clientX: 200, clientY: 500 }],
    })
    await expect(picker).toHaveValue(items[0].id)
    await expect(
      page.getByRole("button", { name: "听示范", exact: true }),
    ).toBeEnabled()
    for (let count = 0; count < 4; count++) {
      await page.getByRole("button", { name: "听示范", exact: true }).click()
      await expect(
        page.getByRole("button", { name: "听示范", exact: true }),
      ).toBeEnabled()
    }
    await expect(page.getByText("今天的路线", { exact: true })).toBeAttached()
    await expect(page.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "0",
    )
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
  })
}

test("@webkit practice blocks switching during recording and can revisit after submission", async ({
  page,
}) => {
  const state = await mockExam(page, false)
  await page.goto("/p/EXAM")
  await page.getByRole("button", { name: "开始录音", exact: true }).click()
  const picker = page.getByRole("combobox", { name: "选择练习题" })
  await expect(picker).toBeDisabled()
  await page.waitForTimeout(1100) // Exercise the minimum valid recording duration.
  await page.getByRole("button", { name: "结束录音", exact: true }).click()
  await expect.poll(() => state.uploads).toBe(1)
  await expect(picker).toBeEnabled()
  await picker.selectOption(items[1].id)
  await picker.selectOption(items[0].id)
  await expect(
    page.getByRole("button", { name: "开始录音", exact: true }),
  ).toBeEnabled()
  await page.getByRole("button", { name: "开始录音", exact: true }).click()
  await page.waitForTimeout(1100) // Exercise the minimum valid recording duration.
  await page.getByRole("button", { name: "结束录音", exact: true }).click()
  await expect.poll(() => state.uploads).toBe(2)
  expect(state.submittedItems).toEqual([items[0].id, items[0].id])
  await expect(page).toHaveURL(/\/p\/EXAM/)
})

for (const nextType of ["repeat", "instruction"]) {
  test(`@webkit pending microphone permission locks navigation to ${nextType}`, async ({
    page,
  }) => {
    const state = await mockExam(page, false, nextType)
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "mediaDevices", {
        configurable: true,
        value: {
          getUserMedia: () =>
            new Promise<MediaStream>((resolve) => {
              ;(window as unknown as { grantMic: () => void }).grantMic = () =>
                resolve(new MediaStream())
            }),
        },
      })
    })
    await page.goto("/p/EXAM")
    await page.getByRole("button", { name: "开始录音", exact: true }).click()
    const picker = page.getByRole("combobox", { name: "选择练习题" })
    await expect(picker).toBeDisabled()
    await expect(
      page
        .getByRole("navigation", { name: "练习选题" })
        .getByRole("button", { name: "下一题", exact: true }),
    ).toBeDisabled()
    const prompt = page.getByText(
      "本题不显示文字。点下方「听示范」听语音，听完后复述出来。",
      { exact: true },
    )
    await prompt.dispatchEvent("touchstart", {
      touches: [{ identifier: 1, clientX: 300, clientY: 300 }],
    })
    await prompt.dispatchEvent("touchend", {
      changedTouches: [{ identifier: 1, clientX: 100, clientY: 300 }],
    })
    await expect(picker).toHaveValue(items[0].id)
    await page.evaluate(() =>
      (window as unknown as { grantMic: () => void }).grantMic(),
    )
    await expect(
      page.getByRole("button", { name: "结束录音", exact: true }),
    ).toBeVisible()
    await page.waitForTimeout(1100)
    await page.getByRole("button", { name: "结束录音", exact: true }).click()
    await expect.poll(() => state.uploads).toBe(1)
    expect(state.submittedItems).toEqual([items[0].id])
  })
}
