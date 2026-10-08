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
      body = {
        id: attemptId,
        item_type: item?.type ?? "passage",
        item_id: item?.id ?? items[0].id,
        session_id: "flow-session",
        engine: "mock",
        duration_s: 3,
        ...(scored ?? { status: "queued" }),
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

test("record → upload → feedback → next item → results page", async ({
  page,
}) => {
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
  await page.getByRole("button", { name: "下一题", exact: true }).click()
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
