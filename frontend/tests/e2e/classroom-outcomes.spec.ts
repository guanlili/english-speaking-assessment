import { expect, type Page, test } from "@playwright/test"
import type { ClassMessagePublic } from "../../src/client"

async function setup(page: Page, lang = "zh") {
  const messages: ClassMessagePublic[] = [
    {
      id: "help",
      student_id: "alice",
      display_name: "Alice Private Name",
      kind: "help",
      category: "audio",
      text: "Cannot hear the recording",
      created_at: "2026-10-18T00:00:00Z",
      read_at: null,
      resolved_at: null,
      resolution: null,
      reply_revision: 0,
    },
  ]
  const state = {
    messages,
    replies: [] as Record<string, unknown>[],
    reminders: [] as Record<string, unknown>[],
    repeats: [] as Record<string, unknown>[],
    failRepeat: true,
    outcomes: 0,
  }
  await page.addInitScript((lang) => {
    localStorage.setItem("access_token", "teacher")
    localStorage.setItem("esa:lang", lang)
  }, lang)
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(),
      url = new URL(req.url()),
      path = url.pathname
    const body = req.method() === "GET" ? null : req.postDataJSON()
    let json: unknown = [],
      status = 200
    if (path.endsWith("/followups"))
      json = [
        {
          id: "task",
          title: "Pet follow-up",
          status: "followup",
          created_at: "2026-10-18T00:00:00Z",
          item_count: 2,
          source_exercise_id: "source",
          targets: [
            {
              student_id: "alice",
              display_name: "Alice",
              done_count: 1,
              total_count: 2,
              has_pending: true,
            },
          ],
        },
      ]
    else if (path.endsWith("/outcomes")) {
      state.outcomes++
      json = {
        task_id: "task",
        title: "Pet follow-up",
        source_title: "Source lesson",
        assigned_at: "2026-10-18T00:00:00Z",
        total_students: 1,
        students: [
          {
            student_id: "alice",
            display_name: "Alice",
            completed_items: 1,
            total_items: 2,
            items: [
              {
                item_id: "item",
                text: "Describe your pet.",
                item_type: "question",
                original: {
                  attempt_id: "original",
                  status: "done",
                  engine: "mock",
                  overall: 60,
                  teacher_feedback: "Add a reason",
                  teacher_focus: true,
                  created_at: "2026-10-17T00:00:00Z",
                },
                followup: {
                  attempt_id: "answer",
                  status: "done",
                  engine: "mock",
                  overall: 80,
                  teacher_feedback: "Clearer explanation",
                  teacher_focus: false,
                  created_at: "2026-10-18T01:00:00Z",
                },
                reference_change: 20,
              },
              {
                item_id: "second",
                text: "Explain your choice.",
                item_type: "question",
                original: null,
                followup: {
                  attempt_id: "queued",
                  status: "queued",
                  engine: "mock",
                  overall: null,
                  teacher_feedback: null,
                  teacher_focus: false,
                  created_at: "2026-10-18T01:00:00Z",
                },
                reference_change: null,
              },
            ],
          },
        ],
      }
    } else if (path.endsWith("/reply")) {
      state.replies.push(body)
      Object.assign(messages[0], {
        reply_text: body.text,
        reply_revision: 1,
        replied_at: "2026-10-18T01:00:00Z",
        read_at: "2026-10-18T01:00:00Z",
        resolved_at: body.resolve ? "2026-10-18T01:00:00Z" : null,
        resolution: body.resolve ? "resolved" : null,
      })
      json = messages[0]
    } else if (path.endsWith("/reminders")) {
      state.reminders.push(body)
      const row: ClassMessagePublic = {
        id: "reminder",
        student_id: "alice",
        display_name: "Alice Private Name",
        kind: "reminder",
        category: null,
        text: body.text,
        created_at: "2026-10-18T00:00:00Z",
        due_at: body.due_at,
        read_at: null,
        resolved_at: null,
        resolution: null,
      }
      messages.push(row)
      json = [row]
    } else if (path.endsWith("/repeat")) {
      state.repeats.push(body)
      if (state.failRepeat) {
        state.failRepeat = false
        status = 503
        json = { detail: "Retry" }
      } else {
        const row = {
          ...messages.find((row) => row.id === "reminder")!,
          id: "repeat",
          reminder_of: "reminder",
        }
        messages.push(row)
        json = row
      }
    } else if (path.endsWith("/read")) {
      const row = messages.find((row) => path.includes(`/${row.id}/`))!
      for (const message of messages.filter(
        (message) =>
          message.id === row.id ||
          message.reminder_of === row.id ||
          message.id === row.reminder_of,
      ))
        message.read_at = "2026-10-18T02:00:00Z"
      json = row
    } else if (path.endsWith("/class-messages"))
      json = messages.filter(
        (row) =>
          row.kind === url.searchParams.get("kind") &&
          (url.searchParams.get("status") !== "open" ||
            (row.kind === "help" ? !row.resolved_at : !row.read_at)),
      )
    else if (path.endsWith("/my-messages")) json = messages
    else if (path.endsWith("/review"))
      json = { revision: 0, notes: {}, summary: "" }
    else if (path.endsWith("/attempts/answer"))
      json = {
        id: "answer",
        item_type: "question",
        status: "done",
        engine: "mock",
        overall: 80,
        teacher_feedback: "Clearer explanation",
        item_text: "Describe your pet.",
      }
    else if (path.endsWith("/learning-report"))
      json = {
        display_name: "Alice",
        session_count: 1,
        completed_items: 1,
        total_items: 2,
        speaking_minutes: 1,
        answers: [],
      }
    await route.fulfill({ status, json })
  })
  return state
}
const fixture = "http://127.0.0.1:5176/teaching-tools.html?p1&compact"
for (const width of [390, 820, 1180]) {
  test(`@webkit compact tools reveal same-item outcomes at ${width}px`, async ({
    page,
  }) => {
    const state = await setup(page)
    await page.setViewportSize({ width, height: 1000 })
    await page.goto(fixture)
    await expect(
      page.getByRole("button", { name: "布置补练", exact: true }),
    ).toBeVisible()
    await expect(page.getByLabel("课堂小结内容")).toBeHidden()
    await expect(
      page.getByRole("button", { name: "查看补练效果", exact: true }),
    ).toBeHidden()
    expect(state.outcomes).toBe(0)
    await page.getByText("查看任务、进度与补练效果", { exact: true }).click()
    await page
      .getByRole("button", { name: "查看补练效果", exact: true })
      .click()
    const dialog = page.getByRole("dialog")
    await expect(
      dialog.getByText("同题参考分变化：+20", { exact: true }),
    ).toBeVisible()
    await expect(
      dialog.getByText("教师评价：Clearer explanation", { exact: true }),
    ).toBeVisible()
    await expect(dialog.getByText("评分中", { exact: true })).toBeVisible()
    await expect(dialog.getByText(/暂不计算参考分变化/)).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - innerWidth,
      ),
    ).toBeLessThanOrEqual(1)
    await page.screenshot({
      path: test.info().outputPath("outcomes.png"),
      fullPage: true,
      animations: "disabled",
    })
    await dialog
      .getByRole("button", { name: "查看补练并点评", exact: true })
      .first()
      .click()
    await expect(
      page.getByRole("heading", { name: "学生作答详情" }),
    ).toBeVisible()
  })
}
test("@webkit teacher reply reaches student and resolved history", async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto(fixture)
  const teacher = page.getByRole("region", { name: "学生求助与站内提醒" })
  await teacher.getByText("答复学生", { exact: true }).click()
  await teacher
    .getByLabel("给学生的答复")
    .fill("Enable sound, then retry playback")
  await teacher.getByRole("button", { name: "发送答复", exact: true }).click()
  await expect.poll(() => state.replies.length).toBe(1)
  expect(state.replies[0]).toEqual({
    text: "Enable sound, then retry playback",
    expected_revision: 0,
    resolve: true,
  })
  await expect(teacher.getByText("暂无待处理求助。")).toBeVisible()
  await teacher.getByLabel("求助记录", { exact: true }).selectOption("all")
  await expect(
    teacher.getByText("教师答复：Enable sound, then retry playback", {
      exact: true,
    }),
  ).toBeVisible()
  await page.reload()
  const inbox = page.getByRole("region", { name: "课堂消息与求助" })
  await expect(
    inbox.getByText("Enable sound, then retry playback", { exact: true }),
  ).toBeVisible()
  await expect(inbox.getByText(/老师已将上次求助标记为处理完成/)).toBeVisible()
})
test("@webkit deadline and unread reminder repeat preserve request identity", async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto(fixture)
  const teacher = page.getByRole("region", { name: "学生求助与站内提醒" })
  await teacher.getByText("向学生发送站内提醒", { exact: true }).click()
  await teacher
    .getByRole("checkbox", { name: "Alice Private Name", exact: true })
    .check()
  await teacher
    .getByLabel("提醒截止时间", { exact: true })
    .fill("2026-12-31T14:00")
  await teacher
    .getByLabel("站内提醒内容", { exact: true })
    .fill("Finish the pet follow-up")
  await teacher
    .getByRole("button", { name: "发送提醒给 1 人", exact: true })
    .click()
  await expect.poll(() => state.reminders.length).toBe(1)
  expect(state.reminders[0].due_at).toMatch(/Z$/)
  await teacher.getByText("最近提醒与已读回执", { exact: true }).click()
  await teacher.getByLabel("提醒状态", { exact: true }).selectOption("open")
  await teacher.getByRole("button", { name: "再次提醒", exact: true }).click()
  await expect(teacher.getByRole("alert")).toBeVisible()
  await teacher.getByRole("button", { name: "再次提醒", exact: true }).click()
  await expect.poll(() => state.repeats.length).toBe(2)
  expect(state.repeats[0]).toEqual(state.repeats[1])
  expect(
    state.messages
      .filter((row) => row.kind === "reminder")
      .every((row) => !row.read_at),
  ).toBe(true)
  await page.reload()
  const inbox = page.getByRole("region", { name: "课堂消息与求助" })
  await expect(inbox.getByText(/^截止：/).first()).toBeVisible()
  await inbox
    .getByRole("button", { name: "我已阅读", exact: true })
    .first()
    .click()
  await expect
    .poll(() =>
      state.messages
        .filter((row) => row.kind === "reminder")
        .every((row) => Boolean(row.read_at)),
    )
    .toBe(true)
})
test("@webkit compact outcome tools and replies have English labels", async ({
  page,
}) => {
  await setup(page, "en")
  await page.setViewportSize({ width: 820, height: 1000 })
  await page.goto(fixture)
  await page
    .getByText("View tasks, progress and outcomes", { exact: true })
    .click()
  await page
    .getByRole("button", { name: "View follow-up outcomes", exact: true })
    .click()
  await expect(
    page
      .getByRole("dialog")
      .getByText("Same-item reference score change: +20", { exact: true }),
  ).toBeVisible()
})
