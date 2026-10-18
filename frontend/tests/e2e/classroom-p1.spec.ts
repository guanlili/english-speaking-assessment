import { expect, type Page, test } from "@playwright/test"

type Message = {
  id: string
  student_id: string
  display_name: string
  kind: string
  category: string | null
  text: string
  created_at: string
  read_at: string | null
  resolved_at: string | null
  resolution: string | null
}
async function setup(page: Page, lang = "zh") {
  const state = {
    revision: 0,
    notes: {} as Record<string, string>,
    summary: "",
    published_summary: null as string | null,
    published_at: null as string | null,
    messages: [] as Message[],
    batches: [] as Record<string, unknown>[],
    conflict: false,
    failBatch: false,
  }
  await page.addInitScript((lang) => {
    localStorage.setItem("access_token", "p1-token")
    localStorage.setItem("esa:lang", lang)
  }, lang)
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname
    const body = request.method() === "GET" ? null : request.postDataJSON()
    let json: unknown = [],
      status = 200
    if (/\/review(?:\/(?:publish|withdraw))?$/.test(path)) {
      if (body) {
        if (state.conflict || body.expected_revision !== state.revision) {
          status = 409
          json = { detail: "Class review revision conflict" }
          state.conflict = false
        } else {
          if (body.attempt_id) state.notes[body.attempt_id] = body.note
          if (body.summary !== undefined) state.summary = body.summary
          if (path.endsWith("/publish")) {
            state.published_summary = state.summary
            state.published_at = "2026-10-17T10:00:00Z"
          }
          if (path.endsWith("/withdraw")) {
            state.published_summary = null
            state.published_at = null
          }
          state.revision++
        }
      }
      if (status === 200)
        json = {
          revision: state.revision,
          notes: state.notes,
          summary: state.summary,
          published_summary: state.published_summary,
          published_at: state.published_at,
        }
    } else if (path.endsWith("/review-summaries"))
      json = state.published_summary
        ? [
            {
              exercise_id: "source",
              title: "Speaking lesson",
              text: state.published_summary,
              published_at: state.published_at,
            },
          ]
        : []
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
        { id: "item", type: "question", text: "Describe your pet." },
        { id: "second", type: "question", text: "Explain your choice." },
      ]
    else if (path.endsWith("/diagnostic-targets"))
      json = {
        source_exercise_id: "source",
        student_ids: ["alice", "ben"],
        item_ids: ["item", "second"],
        matched_answers: 2,
        targets: [
          { student_id: "alice", item_ids: ["item"] },
          { student_id: "ben", item_ids: ["second"] },
        ],
      }
    else if (path.endsWith("/followups/individualized")) {
      state.batches.push(body)
      if (state.failBatch) {
        state.failBatch = false
        status = 503
        json = { detail: "Retry" }
      } else json = { task_ids: ["task-a", "task-b"] }
    } else if (path.endsWith("/help-requests")) {
      const row: Message = {
        id: "help",
        student_id: "alice",
        display_name: "Alice Private Name",
        kind: "help",
        category: body.category,
        text: body.text,
        created_at: "2026-10-17T10:00:00Z",
        read_at: null,
        resolved_at: null,
        resolution: null,
      }
      state.messages.push(row)
      json = row
    } else if (path.endsWith("/reminders")) {
      json = body.student_ids.map((student_id: string) => ({
        id: `reminder-${student_id}`,
        student_id,
        display_name: student_id,
        kind: "reminder",
        category: null,
        text: body.text,
        created_at: "2026-10-17T10:00:00Z",
        read_at: null,
        resolved_at: null,
        resolution: null,
      }))
      state.messages.push(...(json as Message[]))
    } else if (/\/class-messages\/[^/]+\//.test(path)) {
      const [, id, action] = path.match(/\/class-messages\/([^/]+)\/([^/]+)$/)!
      const row = state.messages.find((row) => row.id === id)!
      if (action === "read") row.read_at = "2026-10-17T10:01:00Z"
      else {
        row.resolved_at = "2026-10-17T10:01:00Z"
        row.resolution = action
      }
      json = row
    } else if (path.endsWith("/my-messages"))
      json = state.messages.filter((row) => row.student_id === "alice")
    else if (path.endsWith("/class-messages")) {
      const params = new URL(request.url()).searchParams
      json = state.messages.filter(
        (row) =>
          row.kind === params.get("kind") &&
          (params.get("status") !== "open" || !row.resolved_at),
      )
    } else if (path.endsWith("/attempts/answer"))
      json = {
        id: "answer",
        item_text: "Describe your pet.",
        transcript: "I like cats.",
        duration_s: 3,
      }
    else if (path.endsWith("/learning-report"))
      json = {
        display_name: "Alice",
        completed_items: 0,
        total_items: 2,
        answers: [],
        speaking_minutes: 0,
      }
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(json),
    })
  })
  return state
}
const fixture = "http://127.0.0.1:5176/teaching-tools.html?p1"
for (const width of [390, 820, 1180]) {
  test(`@webkit P1 individualized preview and retry fit ${width}px`, async ({
    page,
  }) => {
    const state = await setup(page)
    state.failBatch = true
    await page.setViewportSize({ width, height: 1000 })
    await page.goto(fixture)
    await page.getByRole("button", { name: "布置补练", exact: true }).click()
    const dialog = page.getByRole("dialog")
    await dialog.getByRole("button", { name: "筛选学生和原题" }).click()
    const preview = dialog.getByRole("region", { name: "逐人补练预览" })
    await expect(
      preview
        .getByRole("group", { name: "Alice Private Name · 1 题" })
        .getByRole("checkbox", { name: "1. Describe your pet." }),
    ).toBeChecked()
    await expect(
      preview
        .getByRole("group", { name: "Ben · 1 题" })
        .getByRole("checkbox", { name: "1. Describe your pet." }),
    ).not.toBeChecked()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - innerWidth,
      ),
    ).toBeLessThanOrEqual(1)
    await page.screenshot({
      path: test.info().outputPath("individual-preview.png"),
      fullPage: true,
    })
    await dialog.getByRole("button", { name: "确认布置给 2 人" }).click()
    await expect(dialog.getByRole("alert")).toBeVisible()
    await dialog.getByRole("button", { name: "确认布置给 2 人" }).click()
    await expect(dialog).toBeHidden()
    expect(state.batches).toHaveLength(2)
    expect(state.batches[0]).toEqual(state.batches[1])
    expect(state.batches[0].targets).toEqual([
      { student_id: "alice", item_ids: ["item"] },
      { student_id: "ben", item_ids: ["second"] },
    ])
  })
}
test("@webkit notes persist, conflicts preserve input, summaries require publication", async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto(fixture)
  await page.getByRole("button", { name: "打开匿名讲评" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog).not.toContainText("Alice Private Name")
  await dialog.getByLabel("亮点与下一步建议").fill("Private teacher advice")
  await dialog.getByRole("button", { name: "保存讲评", exact: true }).click()
  await expect(
    dialog.getByText("已保存到这份练习", { exact: true }),
  ).toBeVisible()
  await page.keyboard.press("Escape")
  await page.reload()
  await page.getByRole("button", { name: "打开匿名讲评" }).click()
  await expect(dialog.getByLabel("亮点与下一步建议")).toHaveValue(
    "Private teacher advice",
  )
  await page.keyboard.press("Escape")
  const summary = page.getByLabel("课堂小结内容")
  await summary.fill("Add a reason to each answer")
  state.conflict = true
  await page.getByRole("button", { name: "保存讲评", exact: true }).click()
  await expect(summary).toHaveValue("Add a reason to each answer")
  await expect(page.getByText(/讲评已在其他页面修改/)).toBeVisible()
  page.once("dialog", (d) => d.accept())
  await page.getByRole("button", { name: /重新加载/ }).click()
  await expect(summary).toHaveValue("")
  await summary.fill("Add a reason to each answer")
  await page.getByRole("button", { name: "保存讲评", exact: true }).click()
  await expect(
    page.getByText("已保存到这份练习", { exact: true }),
  ).toBeVisible()
  expect(state.published_summary).toBeNull()
  page.once("dialog", (d) => d.accept())
  await page.getByRole("button", { name: "发布课堂小结", exact: true }).click()
  const summaries = page.getByRole("region", { name: "老师的课堂小结" })
  await summaries.getByText("Speaking lesson", { exact: true }).click()
  await expect(summaries.getByText("Add a reason to each answer")).toBeVisible()
  await expect(summaries).not.toContainText("Private teacher advice")
})
test("@webkit help resolution and reminders require student acknowledgment", async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto(fixture)
  const inbox = page.getByRole("region", { name: "课堂消息与求助" })
  const teacher = page.getByRole("region", { name: "学生求助与站内提醒" })
  await inbox.getByText("向老师举手求助", { exact: true }).click()
  await inbox.getByLabel("求助补充说明（可选）").fill("My microphone is quiet")
  await inbox.getByRole("button", { name: "发送求助" }).click()
  await expect(inbox.getByText("已向老师求助，等待查看")).toBeVisible()
  await expect(teacher.getByText("My microphone is quiet")).toBeVisible({
    timeout: 12000,
  })
  await teacher.getByRole("button", { name: "标记已查看" }).click()
  await teacher.getByRole("button", { name: "已帮助，标记处理完成" }).click()
  await expect(teacher.getByText("暂无待处理求助。")).toBeVisible()
  await teacher.getByText("向学生发送站内提醒", { exact: true }).click()
  await teacher.getByRole("checkbox", { name: "Alice Private Name" }).check()
  await teacher.getByLabel("站内提醒内容").fill("Please finish question two")
  await teacher.getByRole("button", { name: "发送提醒给 1 人" }).click()
  await expect
    .poll(() => state.messages.filter((row) => row.kind === "reminder").length)
    .toBe(1)
  const reminder = state.messages.find((row) => row.kind === "reminder")!
  expect(reminder.read_at).toBeNull()
  await page.reload()
  await expect(inbox.getByText("Please finish question two")).toBeVisible()
  expect(reminder.read_at).toBeNull()
  await inbox.getByRole("button", { name: "我已阅读" }).click()
  await expect(inbox.getByText("你已标记为已读")).toBeVisible()
  expect(reminder.read_at).not.toBeNull()
})

test("@webkit P1 controls provide English labels at tablet width", async ({
  page,
}) => {
  await setup(page, "en")
  await page.setViewportSize({ width: 820, height: 1100 })
  await page.goto(fixture)
  await expect(
    page.getByRole("heading", { name: "Student help and reminders" }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Send help request" }),
  ).toBeHidden()
  await page.getByText("Raise your hand for help", { exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Send help request" }),
  ).toBeVisible()
  await expect(page.getByLabel("Class summary text")).toBeVisible()
  await page
    .getByRole("button", { name: "Assign targeted practice", exact: true })
    .click()
  const dialog = page.getByRole("dialog")
  await dialog
    .getByRole("button", { name: "Find students and source items" })
    .click()
  await expect(
    dialog.getByRole("region", { name: "Individual practice preview" }),
  ).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - innerWidth,
    ),
  ).toBeLessThanOrEqual(1)
})
