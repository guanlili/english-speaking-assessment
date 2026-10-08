import { expect, type Page, test } from "@playwright/test"
import type { PlanAttempt } from "../../src/client/types.gen"

const items = [0, 1].map((index) => ({
  id: `00000000-0000-4000-8000-00000000000${index + 1}`,
  type: "passage",
  text: `Timed article ${index + 1}.`,
  suggested_seconds: 3,
}))

async function mockExam(page: Page, isExam = true) {
  const state = {
    index: 0,
    ended: false,
    attempts: [] as PlanAttempt[],
    uploads: 0,
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
        this.ondataavailable?.(
          new BlobEvent("dataavailable", {
            data: new Blob(["test audio"], { type: "audio/webm" }),
          }),
        )
        queueMicrotask(() => this.onstop?.())
      }
    }
    window.MediaRecorder = TestRecorder as unknown as typeof MediaRecorder
    navigator.mediaDevices.getUserMedia = async () => new MediaStream()
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
            : items,
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
      const item = items[state.index]
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
        item_type: "passage",
        item_id: item.id,
        session_id: "exam-session",
        status: "queued",
        engine: "mock",
        duration_s: 3,
      }
    } else if (path.includes("/attempts/"))
      body = {
        id: "attempt-0",
        item_type: "passage",
        item_id: items[0].id,
        status: "queued",
        engine: "mock",
        duration_s: 3,
      }
    await route.fulfill({ json: body })
  })
  return state
}

async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1)
}

for (const width of [390, 820, 1180]) {
  test(`exam timeout advances unanswered items and locks results at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.clock.install()
    const state = await mockExam(page)
    await page.goto("/p/EXAM?focus=ignored-old-item")
    await expect(page.getByText(items[0].text, { exact: true })).toBeVisible()
    await expect(page.getByTestId("exam-item-timer")).toBeVisible()
    await noOverflow(page)
    state.index = 1
    await page.clock.runFor(3500)
    await expect(page.getByText(items[1].text, { exact: true })).toBeVisible()
    // 刷新不会回到未提交但已到时的第一题，focus 也不能回题。
    await page.goto(`/p/EXAM?focus=${items[0].id}`)
    await expect(page.getByText(items[1].text, { exact: true })).toBeVisible()
    state.ended = true
    state.index = 2
    await page.clock.runFor(3500)
    await expect(page).toHaveURL(/\/p\/EXAM\/result/)
    await expect(page.getByText(/未作答 2 题/)).toBeVisible()
    await expect(
      page.getByRole("button", { name: /再练|重练|换同主题/ }),
    ).toHaveCount(0)
    await expect(page.getByRole("link", { name: "返回首页" })).toBeVisible()
    await noOverflow(page)
    expect(state.uploads).toBe(0)
  })
}

test("exam timeout submits and advances while scoring remains queued", async ({
  page,
}) => {
  await page.clock.install()
  const state = await mockExam(page)
  await page.goto("/p/EXAM")
  await page.getByRole("button", { name: "开始录音", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "结束录音", exact: true }),
  ).toBeVisible()
  await page.clock.runFor(3500)
  await expect(page.getByText(items[1].text, { exact: true })).toBeVisible()
  await expect(
    page.getByRole("button", { name: "开始录音", exact: true }),
  ).toBeEnabled()
  expect(state.attempts[0].status).toBe("queued")
  expect(state.uploads).toBe(1)
  await page.getByRole("button", { name: "开始录音", exact: true }).click()
  await page.clock.runFor(3500)
  await expect(page).toHaveURL(/\/p\/EXAM\/result/)
  await expect(page.getByText("录音正在评分，结果会自动更新")).toBeVisible()
  expect(state.uploads).toBe(2)
})

test("exam upload failure retains original recording without re-recording", async ({
  page,
}) => {
  await page.clock.install()
  const state = await mockExam(page)
  state.failUpload = true
  await page.goto("/p/EXAM")
  await page.getByRole("button", { name: "开始录音", exact: true }).click()
  await page.clock.runFor(3500)
  await expect(
    page.getByRole("button", { name: "重传录音", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "重新录", exact: true }),
  ).toHaveCount(0)
  state.failUpload = false
  await page.getByRole("button", { name: "重传录音", exact: true }).click()
  await expect(page.getByText(items[1].text, { exact: true })).toBeVisible()
  expect(state.uploads).toBe(1)
})

test("regular practice retains result re-practice controls", async ({
  page,
}) => {
  const state = await mockExam(page, false)
  state.attempts.push({
    item_id: items[0].id,
    attempt_id: "attempt-0",
    status: "done",
    overall: 80,
  })
  await page.goto("/p/EXAM/result")
  await expect(
    page.getByRole("button", { name: "重练最弱的一题" }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "换同主题下一问" }),
  ).toBeVisible()
  await page.getByRole("button", { name: "回听这一题" }).click()
  await expect(page.getByRole("button", { name: "再练这一题" })).toBeVisible()
})

test("completed exam permits playback but no re-practice", async ({ page }) => {
  const state = await mockExam(page)
  state.ended = true
  state.attempts.push({
    item_id: items[0].id,
    attempt_id: "attempt-0",
    status: "done",
    overall: 80,
  })
  await page.goto("/p/EXAM/result")
  await page.getByRole("button", { name: "回听这一题" }).click()
  await expect(page.getByRole("dialog")).toBeVisible()
  await expect(page.getByRole("button", { name: "再练这一题" })).toHaveCount(0)
})

test("exam prep time gates recording and cannot be skipped", async ({
  page,
}) => {
  await page.clock.install()
  const state = await mockExam(page)
  state.prepSeconds = 2
  await page.goto("/p/EXAM")
  await expect(
    page.getByRole("button", { name: "开始录音", exact: true }),
  ).toBeDisabled()
  await expect(
    page.getByRole("button", { name: "跳过准备，直接开始" }),
  ).toHaveCount(0)
  await expect(page.getByTestId("exam-item-timer")).toContainText("准备倒计时")
  await page.clock.runFor(2300)
  await expect(
    page.getByRole("button", { name: "开始录音", exact: true }),
  ).toBeEnabled()
  await expect(page.getByTestId("exam-item-timer")).toContainText("本题倒计时")
})

test("late microphone permission cannot start recording an expired item", async ({
  page,
}) => {
  await page.clock.install()
  const state = await mockExam(page)
  await page.goto("/p/EXAM")
  await page.evaluate(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      await new Promise<void>((resolve) => window.setTimeout(resolve, 5000))
      return new MediaStream()
    }
  })
  await page.getByRole("button", { name: "开始录音", exact: true }).click()
  state.index = 1
  await page.clock.runFor(3500)
  await expect(page.getByText(items[1].text, { exact: true })).toBeVisible()
  await page.clock.runFor(2000)
  await expect(
    page.getByRole("button", { name: "结束录音", exact: true }),
  ).toHaveCount(0)
  expect(state.uploads).toBe(0)
})
