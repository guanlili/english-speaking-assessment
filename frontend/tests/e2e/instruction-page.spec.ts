import { expect, type Page, test } from "@playwright/test"
import type { PlanAttempt } from "../../src/client/types.gen"

/** 题目说明（第四题型）：练习模式点「继续」推进；模考中计时窗口/提前继续/到时自动翻页。 */

const instruction = {
  id: "00000000-0000-4000-8000-000000000010",
  type: "instruction",
  title: "Part B 开始",
  text: "Welcome to Part B. Take a breath and read carefully.",
  suggested_seconds: 5,
}
const passage = {
  id: "00000000-0000-4000-8000-000000000011",
  type: "passage",
  text: "The ocean covers most of our planet.",
  suggested_seconds: 8,
}

async function mockPlan(page: Page, isExam: boolean) {
  const state = {
    index: 0,
    acks: 0,
    ackedAt: null as string | null,
    attempts: [] as PlanAttempt[],
  }
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token")
    localStorage.setItem("esa:role", "student")
    localStorage.setItem(
      "esa:student:INS",
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
    else if (path.endsWith("/acks")) {
      state.acks += 1
      state.index = 1
      state.ackedAt = "2026-10-08T12:00:00Z"
      body = { acked: true, acked_at: state.ackedAt }
    } else if (path.endsWith("/today"))
      body = {
        session_id: "ins-session",
        classroom_code: "INS",
        band: "B1",
        // 深拷贝防跨用例泄漏（acked_at 只反映本用例的 ack 状态）
        items: [{ ...instruction, acked_at: state.ackedAt }, { ...passage }],
        attempts: state.attempts,
        exam: isExam
          ? {
              started: true,
              ended: false,
              time_limit_minutes: 30,
              remaining_seconds: 1800,
              current_item_index: state.index,
              item_remaining_seconds: 5,
              prep_remaining_seconds: 0,
            }
          : null,
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
  test(`practice instruction page advances on continue at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    const state = await mockPlan(page, false)
    await page.goto("/p/INS")
    // 说明卡：标题 + 文案 + 继续按钮；没有录音按钮
    await expect(page.getByText(instruction.title)).toBeVisible()
    await expect(page.getByText(instruction.text)).toBeVisible()
    await expect(page.getByRole("button", { name: /开始录音/ })).toHaveCount(0)
    await noOverflow(page)
    await page.getByRole("button", { name: /继续/ }).click()
    // 乐观推进到朗读题；ack 已上报
    await expect(page.getByText(passage.text)).toBeVisible()
    await expect(page.getByRole("button", { name: /开始录音/ })).toBeVisible()
    expect(state.acks).toBe(1)
    await noOverflow(page)
  })
}

test("exam instruction window: continue early posts ack and advances", async ({
  page,
}) => {
  const state = await mockPlan(page, true)
  await page.goto("/p/INS")
  await expect(page.getByText(instruction.text)).toBeVisible()
  await expect(page.getByTestId("exam-item-timer")).toBeVisible()
  await page.getByRole("button", { name: /继续/ }).click()
  await expect(page.getByText(passage.text)).toBeVisible()
  expect(state.acks).toBe(1)
})

test("exam instruction window auto-advances on timeout without ack", async ({
  page,
}) => {
  await page.clock.install()
  const state = await mockPlan(page, true)
  await page.goto("/p/INS")
  await expect(page.getByText(instruction.text)).toBeVisible()
  // 服务端到时推进（此处由 mock 直接推进 index），前端倒计时归零后刷新题单
  state.index = 1
  await page.clock.runFor(5500)
  await expect(page.getByText(passage.text)).toBeVisible()
  expect(state.acks).toBe(0)
})
