import { expect, type Page, test } from "@playwright/test"

async function setup(page: Page, lang = "zh") {
  const state = {
    requests: [] as { path: string; body: Record<string, unknown> | null }[],
  }
  await page.addInitScript((lang) => {
    localStorage.setItem("access_token", "teacher-token")
    localStorage.setItem("esa:lang", lang)
  }, lang)
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const body =
      route.request().method() === "GET" ? null : route.request().postDataJSON()
    state.requests.push({ path, body })
    let json: unknown = []
    if (path.endsWith("/presence"))
      json = [
        {
          student_id: "alice",
          display_name: "Alice Private Name",
          activity: "recording",
          device_check: "passed",
        },
      ]
    else if (path.endsWith("/exercises"))
      json = [
        {
          id: "source",
          title: "Speaking lesson",
          version_no: 1,
          is_exam: false,
        },
      ]
    else if (path.endsWith("/followup-items"))
      json = [
        { id: "item", type: "question", text: "Describe your favorite pet." },
      ]
    else if (path.endsWith("/diagnostic-targets"))
      json = {
        source_exercise_id: "source",
        student_ids: ["alice"],
        item_ids: ["item"],
        matched_answers: 1,
      }
    else if (path.endsWith("/learning-report"))
      json = {
        display_name: "Alice Private Name",
        start_date: "2026-10-11",
        end_date: "2026-10-17",
        session_count: 2,
        completed_items: 1,
        total_items: 2,
        speaking_minutes: 3,
        reading_avg: 80,
        question_avg: 72,
        answers: [],
        has_active_exam: true,
      }
    else if (path.endsWith("/comparison"))
      json = [
        {
          id: "first",
          status: "done",
          item_type: "question",
          overall: 60,
          transcript: "I like cats.",
        },
        {
          id: "latest",
          status: "done",
          item_type: "question",
          overall: 80,
          transcript: "I like cats because they are friendly.",
        },
      ]
    else if (path.endsWith("/content/question/source-item"))
      json = {
        id: "source-item",
        title: "Source lesson",
        text: "Original shared question",
        author_name: "Source teacher",
      }
    else if (path.endsWith("/copy"))
      json = { id: "copy", copied_from_id: "item" }
    else if (path.endsWith("/teacher-feedback"))
      json = {
        id: "answer",
        teacher_feedback: body?.text,
        teacher_review_tags: body?.review_tags,
        teacher_feedback_revision: 1,
      }
    else if (path.endsWith("/revision")) json = { revision: "ok" }
    else if (path.endsWith("/attempts/answer"))
      json = {
        id: "answer",
        item_text: "Describe your favorite pet.",
        transcript: "I like cats.",
        duration_s: 3,
      }
    else if (path.endsWith("/audio")) {
      await route.fulfill({
        status: 200,
        contentType: "audio/wav",
        body: Buffer.alloc(44),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(json),
    })
  })
  return state
}
const fixture = "http://127.0.0.1:5176/teaching-tools.html"
for (const width of [390, 820, 1180]) {
  test(`@webkit teaching tools fit ${width}px and confirm diagnostic recipients`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    const state = await setup(page)
    await page.goto(fixture)
    await expect(page.getByText("Alice Private Name · 正在录音")).toBeVisible()
    await expect(page.getByText("设备自检通过", { exact: true })).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - innerWidth,
      ),
    ).toBeLessThanOrEqual(1)
    await page.screenshot({
      path: test.info().outputPath("tools.png"),
      fullPage: true,
    })
    await page.getByRole("button", { name: "布置补练", exact: true }).click()
    const dialog = page.getByRole("dialog")
    await dialog.getByRole("combobox").first().selectOption("short_answer")
    await dialog.getByRole("button", { name: "筛选学生和原题" }).click()
    await expect(dialog.getByText(/匹配 1 人、1 题/)).toBeVisible()
    await expect(
      dialog.getByRole("checkbox", { name: "Alice Private Name" }),
    ).toBeChecked()
    expect(
      state.requests.filter(
        (row) => row.path.endsWith("/followups") && row.body,
      ),
    ).toHaveLength(0)
    await dialog.getByRole("button", { name: "确认布置给 1 人" }).click()
    await expect
      .poll(
        () =>
          state.requests.find(
            (row) => row.path.endsWith("/followups") && row.body,
          )?.body?.student_ids,
      )
      .toEqual(["alice"])
    await expect(dialog).toBeHidden()
  })
}
test("@webkit anonymous discussion omits names and comparison shows both answers", async ({
  page,
}) => {
  await setup(page)
  await page.goto(fixture)
  await page.getByRole("button", { name: "打开匿名讲评" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByText("I like cats.", { exact: true })).toBeVisible()
  await expect(dialog).not.toContainText("Alice Private Name")
  await page.screenshot({ path: test.info().outputPath("discussion.png") })
  await dialog
    .getByLabel("亮点与下一步建议")
    .fill("Clear opening; add a reason.")
  await page.keyboard.press("Escape")
  await page.getByRole("button", { name: "对比首次与最近一次作答" }).click()
  await expect(page.getByRole("heading", { name: "首次作答" })).toBeVisible()
  await expect(
    page.getByText("I like cats because they are friendly."),
  ).toBeVisible()
})
test("@webkit review tags and copies persist through generated APIs", async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto(fixture)
  await page.getByRole("checkbox", { name: "AI 转写有误", exact: true }).check()
  await page
    .getByRole("textbox", { name: "教师点评内容" })
    .fill("Listen again and add a detail.")
  await page.getByRole("button", { name: "保存教师点评", exact: true }).click()
  await expect
    .poll(
      () =>
        state.requests.find((row) => row.path.endsWith("/teacher-feedback"))
          ?.body?.review_tags,
    )
    .toEqual(["transcript_error"])
  await page.getByRole("button", { name: "查看副本来源" }).click()
  await expect(page.getByRole("dialog")).toContainText("Source teacher")
  await page.keyboard.press("Escape")
  await page.getByRole("button", { name: "复制为我的版本" }).click()
  await expect
    .poll(() =>
      state.requests.some((row) =>
        row.path.endsWith("/content/question/item/copy"),
      ),
    )
    .toBe(true)
})
test("@webkit English report changes period and preflight reports microphone failure", async ({
  page,
}) => {
  const state = await setup(page, "en")
  await page.addInitScript(() => {
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
      value: () => Promise.reject(new Error("denied")),
    })
  })
  await page.goto(fixture)
  await expect(
    page.getByRole("heading", { name: "Learning report" }),
  ).toBeVisible()
  await page.getByLabel("Period", { exact: true }).selectOption("30")
  await page.getByRole("button", { name: "Record a 5-second test" }).click()
  await expect(page.getByRole("alert")).toContainText(
    "Check microphone permissions",
  )
  await expect
    .poll(
      () =>
        state.requests.find((row) => row.path.endsWith("/activity"))?.body
          ?.device_check,
    )
    .toBe("failed")
})

test("@webkit preflight requires playback confirmation before reporting success", async ({
  page,
}) => {
  const state = await setup(page)
  await page.clock.install()
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
      },
    })
    class TestRecorder {
      state = "inactive"
      mimeType = "audio/wav"
      ondataavailable: ((event: { data: Blob }) => void) | null = null
      onstop: (() => void) | null = null
      start() {
        this.state = "recording"
      }
      stop() {
        this.state = "inactive"
        const data = new ArrayBuffer(44 + 16000)
        const view = new DataView(data)
        const write = (offset: number, text: string) => {
          for (let i = 0; i < text.length; i++)
            view.setUint8(offset + i, text.charCodeAt(i))
        }
        write(0, "RIFF")
        view.setUint32(4, data.byteLength - 8, true)
        write(8, "WAVE")
        write(12, "fmt ")
        view.setUint32(16, 16, true)
        view.setUint16(20, 1, true)
        view.setUint16(22, 1, true)
        view.setUint32(24, 8000, true)
        view.setUint32(28, 16000, true)
        view.setUint16(32, 2, true)
        view.setUint16(34, 16, true)
        write(36, "data")
        view.setUint32(40, 16000, true)
        this.ondataavailable?.({
          data: new Blob([data], { type: "audio/wav" }),
        })
        this.onstop?.()
      }
    }
    window.MediaRecorder = TestRecorder as unknown as typeof MediaRecorder
  })
  await page.goto(fixture)
  await page.getByRole("button", { name: "开始 5 秒试录" }).click()
  await expect(
    page.getByRole("button", { name: "试录中，请说一句英语…" }),
  ).toBeDisabled()
  await page.clock.runFor(5100)
  const confirm = page.getByRole("button", { name: "听得清楚，检查课堂连接" })
  await expect(confirm).toBeVisible({ timeout: 10000 })
  await expect(confirm).toBeDisabled()
  expect(
    state.requests.some(
      (row) =>
        row.path.endsWith("/activity") && row.body?.device_check === "passed",
    ),
  ).toBe(false)
  await page.locator("audio[controls]").dispatchEvent("ended")
  await confirm.click()
  await expect(page.getByText("试录、回放和课堂连接检查通过。")).toBeVisible()
  await expect
    .poll(
      () =>
        state.requests.find((row) => row.path.endsWith("/activity"))?.body
          ?.device_check,
    )
    .toBe("passed")
  expect(
    state.requests.some(
      (row) =>
        row.path.includes("/exam/start") || row.path.endsWith("/attempts"),
    ),
  ).toBe(false)
})
