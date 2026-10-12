import { expect, type Page, test } from "@playwright/test"

const published = ["old", "new"].map((id, index) => ({
  id,
  title: `${id} publish`,
  version_no: index + 1,
  status: index ? "published" : "archived",
  item_count: 2,
  is_exam: false,
  published_at: "2026-10-01T10:00:00Z",
}))
const items = (version: string) => [
  {
    item_id: "instructions",
    type: "instruction",
    status: "done",
    attempt_id: "secret-instruction",
  },
  {
    item_id: "q1",
    type: "question",
    status: "done",
    overall: 80,
    attempt_id: `${version}-1`,
  },
  {
    item_id: "q2",
    type: "passage",
    status: "done",
    overall: 60,
    attempt_id: `${version}-2`,
  },
]
async function mockTeacher(page: Page, nativeAudio = false) {
  const state = {
    requested: [] as string[],
    audio: [] as string[],
    fail: false,
    slow: false,
    failAudio: false,
    engine: "ark",
    rubric: null as Record<string, unknown> | null,
  }
  await page.addInitScript((nativeAudio) => {
    localStorage.setItem("access_token", "teacher-token")
    localStorage.setItem("esa:role", "teacher")
    if (nativeAudio) return
    const status = new WeakMap<HTMLMediaElement, boolean>()
    Object.defineProperty(HTMLMediaElement.prototype, "paused", {
      get() {
        return !status.get(this)
      },
    })
    HTMLMediaElement.prototype.play = function () {
      if ((window as unknown as { rejectPlay: boolean }).rejectPlay)
        return Promise.reject(new Error("blocked"))
      status.set(this, true)
      this.dispatchEvent(new Event("play"))
      return Promise.resolve()
    }
    HTMLMediaElement.prototype.pause = function () {
      status.set(this, false)
      this.dispatchEvent(new Event("pause"))
    }
  }, nativeAudio)
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    const row = (version: string) => ({
      student_id: "student",
      display_name: "Alice",
      done_count: 2,
      total_count: 2,
      has_pending: false,
      items: items(version),
      repeat_avg: 60,
      question_avg: 80,
      round_status: "all_done",
    })
    if (path.endsWith("/users/me"))
      body = { id: "teacher", role: "teacher", is_active: true }
    else if (path.endsWith("/board"))
      body = {
        classroom_code: "TEACH",
        classroom_name: "Teacher class",
        class_size: 10,
        engine: "ark",
        current_exercise: published[1],
        submitted_count: 1,
        completed_count: 1,
        pending_count: 0,
        students: [row("new")],
        items: items("new"),
      }
    else if (path.endsWith("/exercises")) body = published
    else if (path.endsWith("/results"))
      body = [row(path.includes("/old/") ? "old" : "new")]
    else if (path.includes("/attempts/")) {
      const id = path.split("/attempts/")[1].split("/")[0]
      if (path.endsWith("/audio")) {
        state.audio.push(id)
        if (state.failAudio) {
          await route.fulfill({ status: 503, body: "temporary" })
          return
        }
        expect(route.request().headers().authorization).toBe(
          "Bearer teacher-token",
        )
        if (state.slow && id.endsWith("1"))
          await new Promise((resolve) => setTimeout(resolve, 300))
        await route.fulfill({
          contentType: "audio/wav",
          body: Buffer.from("recording"),
        })
        return
      }
      state.requested.push(id)
      if (state.fail) {
        await route.fulfill({ status: 503, json: { detail: "temporary" } })
        return
      }
      body = {
        id,
        item_id: id.endsWith("1") ? "q1" : "q2",
        item_type: id.endsWith("1") ? "question" : "passage",
        status: "done",
        overall: id.endsWith("1") ? 80 : 60,
        engine: state.engine,
        rubric: id.endsWith("1") ? state.rubric : null,
        duration_s: 5,
        item_text: `Saved prompt ${id}`,
        advice: [`Saved rule advice ${id}`],
      }
    }
    await route.fulfill({ json: body })
  })
  return state
}
async function openHistory(page: Page) {
  await page.goto("/t/TEACH")
  await page.getByRole("tab", { name: /发布历史/ }).click()
  await page
    .getByRole("button", { name: "查看结果", exact: true })
    .first()
    .click()
}
for (const width of [390, 820, 1180]) {
  test(`@webkit historical feedback uses actual publish attempts at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const state = await mockTeacher(page)
    await openHistory(page)
    if (width < 1024) {
      expect(
        await page
          .locator('[data-slot="table-container"]')
          .evaluateAll((elements) =>
            elements.every(
              (element) => element.scrollWidth <= element.clientWidth,
            ),
          ),
      ).toBe(true)
    }
    await page.getByRole("button", { name: "汇总反馈", exact: true }).click()
    const dialog = page.getByRole("dialog")
    await expect(dialog.getByText("Saved rule advice old-1")).toBeVisible()
    await expect(dialog.getByText("Saved rule advice old-2")).toBeVisible()
    await expect(dialog.getByText("已评分 2/2 题 · 参考分 70")).toBeVisible()
    expect(state.requested.sort()).toEqual(["old-1", "old-2"])
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
  })
}
test("@webkit history recording starts with one click and switches exclusively", async ({
  page,
}) => {
  const state = await mockTeacher(page)
  await openHistory(page)
  const first = page.getByRole("button", {
    name: "回听 Alice 第2题录音",
    exact: true,
  })
  const second = page.getByRole("button", {
    name: "回听 Alice 第3题录音",
    exact: true,
  })
  await first.click()
  await expect(first).toHaveAttribute("aria-pressed", "true")
  await second.click()
  await expect(second).toHaveAttribute("aria-pressed", "true")
  await expect(first).toHaveAttribute("aria-pressed", "false")
  await second.click()
  await expect(second).toHaveAttribute("aria-pressed", "false")
  expect(state.audio).toEqual(["old-1", "old-2"])
})
test("@webkit feedback loading failure can retry without closing", async ({
  page,
}) => {
  const state = await mockTeacher(page)
  state.fail = true
  await openHistory(page)
  await page.getByRole("button", { name: "汇总反馈", exact: true }).click()
  const retry = page
    .getByRole("dialog")
    .getByRole("button", { name: "反馈加载失败，重试" })
    .first()
  await expect(retry).toBeVisible()
  state.fail = false
  await retry.click()
  await expect(
    page.getByRole("dialog").getByText("Saved rule advice old-1"),
  ).toBeVisible()
})
test("@webkit playback rejection retries at the same button", async ({
  page,
}) => {
  await mockTeacher(page)
  await openHistory(page)
  await page.evaluate(() => {
    ;(window as unknown as { rejectPlay: boolean }).rejectPlay = true
  })
  const button = page.getByRole("button", {
    name: "回听 Alice 第2题录音",
    exact: true,
  })
  await button.click()
  await expect(page.getByRole("alert")).toContainText("播放未成功")
  await page.evaluate(() => {
    ;(window as unknown as { rejectPlay: boolean }).rejectPlay = false
  })
  await button.click()
  await expect(button).toHaveAttribute("aria-pressed", "true")
})
test("@webkit current roster offers the same feedback and listening controls", async ({
  page,
}) => {
  const state = await mockTeacher(page)
  await page.goto("/t/TEACH")
  await page.getByRole("tab", { name: /学生.*结果|课堂面板|学生反馈/ }).click()
  await page.getByRole("button", { name: "汇总反馈", exact: true }).click()
  await expect(
    page.getByRole("dialog").getByText("Saved rule advice new-1"),
  ).toBeVisible()
  await page.getByRole("button", { name: "关闭", exact: true }).click()
  await page.getByRole("button", { name: "展开 Alice 的详情" }).click()
  const button = page.getByRole("button", {
    name: "回听 Alice 第2题录音",
    exact: true,
  })
  await button.click()
  await expect(button).toHaveAttribute("aria-pressed", "true")
  expect(state.audio).toEqual(["new-1"])
})

test("@webkit a slow earlier recording cannot interrupt the latest selection", async ({
  page,
}) => {
  const state = await mockTeacher(page)
  state.slow = true
  await openHistory(page)
  const first = page.getByRole("button", {
    name: "回听 Alice 第2题录音",
    exact: true,
  })
  const second = page.getByRole("button", {
    name: "回听 Alice 第3题录音",
    exact: true,
  })
  await first.click()
  await second.click()
  await expect(second).toHaveAttribute("aria-pressed", "true")
  await expect(first).toBeEnabled()
  await expect(first).toHaveAttribute("aria-pressed", "false")
  await expect(second).toHaveAttribute("aria-pressed", "true")
})

test("@webkit one click starts real browser audio without native controls", async ({
  page,
}) => {
  await mockTeacher(page, true)
  const wav = Buffer.alloc(44 + 16000 * 2 * 3)
  wav.write("RIFF", 0)
  wav.writeUInt32LE(wav.length - 8, 4)
  wav.write("WAVEfmt ", 8)
  wav.writeUInt32LE(16, 16)
  wav.writeUInt16LE(1, 20)
  wav.writeUInt16LE(1, 22)
  wav.writeUInt32LE(16000, 24)
  wav.writeUInt32LE(32000, 28)
  wav.writeUInt16LE(2, 32)
  wav.writeUInt16LE(16, 34)
  wav.write("data", 36)
  wav.writeUInt32LE(wav.length - 44, 40)
  await page.route("**/attempts/old-1/audio", (route) =>
    route.fulfill({ contentType: "audio/wav", body: wav }),
  )
  await openHistory(page)
  const button = page.getByRole("button", {
    name: "回听 Alice 第2题录音",
    exact: true,
  })
  await button.click()
  await expect(button).toHaveAttribute("aria-pressed", "true")
  const audio = button.locator("..").locator("audio")
  await expect
    .poll(() =>
      audio.evaluate((element: HTMLAudioElement) => element.currentTime),
    )
    .toBeGreaterThan(0)
  await expect(audio).not.toHaveAttribute("controls")
})

test("@webkit failed audio download retries in place", async ({ page }) => {
  const state = await mockTeacher(page)
  state.failAudio = true
  await openHistory(page)
  const button = page.getByRole("button", {
    name: "回听 Alice 第2题录音",
    exact: true,
  })
  await button.click()
  await expect(page.getByRole("alert")).toContainText("播放未成功")
  state.failAudio = false
  await button.click()
  await expect(button).toHaveAttribute("aria-pressed", "true")
  expect(state.audio).toEqual(["old-1", "old-1"])
})

for (const source of [
  "mock",
  "rules-only",
  "pending",
  "unavailable",
  "model",
]) {
  test(`@webkit summary identifies feedback source: ${source}`, async ({
    page,
  }) => {
    const state = await mockTeacher(page)
    state.engine = source === "mock" ? "mock" : "ark"
    state.rubric =
      source === "model"
        ? {
            fluency: 3,
            vocabulary: 3,
            grammar: 3,
            task: 3,
            mock_score: 6.5,
            advice: ["Saved model review"],
          }
        : source === "pending" || source === "unavailable"
          ? { status: source }
          : null
    await openHistory(page)
    await page.getByRole("button", { name: "汇总反馈", exact: true }).click()
    const dialog = page.getByRole("dialog")
    await expect(dialog.getByText(/并非独立生成的整轮 AI 总评/)).toBeVisible()
    await expect(
      dialog.getByText("规则评分与建议", { exact: true }),
    ).toHaveCount(2)
    await expect(dialog.getByText("Saved rule advice old-1")).toBeVisible()
    const expected = {
      mock: "演示模式 · 本地模拟引擎",
      "rules-only": "模拟分：本次建议暂缺（模型未返回）",
      pending: "详细评价正在生成…",
      unavailable: "详细评价暂缺，请稍后再试。",
      model: "Saved model review",
    }[source]!
    await expect(
      dialog.getByText(expected, { exact: true }).first(),
    ).toBeVisible()
    if (source === "mock")
      await expect(
        dialog.getByText("暂无模型评价。", { exact: true }),
      ).toBeVisible()
    if (source !== "model")
      await expect(dialog.getByText("Saved model review")).toHaveCount(0)
  })
}

for (const width of [390, 820, 1180]) {
  test(`@webkit current roster remains usable in both languages at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    await mockTeacher(page)
    await page.goto("/t/TEACH")
    await page.getByRole("tab", { name: "学生结果", exact: true }).click()
    const expand = page.getByRole("button", {
      name: "展开 Alice 的详情",
      exact: true,
    })
    await expect(expand).toBeVisible()
    expect((await expand.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    await page.getByRole("button", { name: "汇总反馈", exact: true }).click()
    await expect(
      page.getByRole("dialog").getByText("Saved rule advice new-1"),
    ).toBeVisible()
    await page.getByRole("button", { name: "关闭", exact: true }).click()
    await expand.click()
    const play = page.getByRole("button", {
      name: "回听 Alice 第2题录音",
      exact: true,
    })
    await play.click()
    await expect(play).toHaveAttribute("aria-pressed", "true")
    await play.click()
    await page
      .getByRole("searchbox", { name: "搜索学生姓名", exact: true })
      .fill("Nobody")
    await expect(
      page.getByText("没有找到符合条件的学生", { exact: true }),
    ).toBeVisible()
    await page
      .getByRole("button", { name: "查看全部学生", exact: true })
      .click()
    await expect(page.getByText("Alice", { exact: true })).toBeVisible()
    for (const language of ["中", "EN"]) {
      await page
        .getByRole("button", { name: language, exact: true })
        .last()
        .click()
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true)
      // Expanded content must fit its card, including at phone width.
      const table = page.locator('[data-slot="table-container"]').first()
      expect(
        await table.evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
      ).toBe(true)
    }
    await expect(
      page.getByRole("button", { name: "Overall feedback", exact: true }),
    ).toBeVisible()
    await page
      .getByRole("button", { name: "Collapse details for Alice", exact: true })
      .click()
  })
}
