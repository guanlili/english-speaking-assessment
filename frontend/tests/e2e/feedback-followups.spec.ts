import { expect, type Page, test } from "@playwright/test"
import type { AttemptPublic, FollowupPublic } from "../../src/client"

const item = {
  id: "item",
  type: "passage",
  text: "Original frozen speaking prompt.",
  suggested_seconds: 30,
}
const exercise = {
  id: "source",
  classroom_id: "class",
  version_no: 1,
  title: "Original class practice",
  status: "published",
  item_count: 1,
  is_exam: false,
}
async function setup(page: Page, role: "teacher" | "student", lang = "zh") {
  const state = {
    attempt: {
      id: "answer",
      item_id: item.id,
      item_type: "passage",
      student_id: "alice",
      session_id: "original-session",
      status: "done",
      engine: "mock",
      duration_s: 4,
      overall: 88,
      transcript: "Original answer.",
      teacher_feedback: "",
      teacher_focus: false,
      teacher_feedback_revision: 0,
    } as AttemptPublic,
    sourceItems: [item],
    tasks: [] as FollowupPublic[],
    bodies: [] as { student_ids: string[]; item_ids: string[] }[],
    fail: false,
    conflict: false,
    started: 0,
    failList: false,
    followupRequests: [] as { status: string; offset: number; limit: number }[],
  }
  page.on("dialog", (dialog) => void dialog.accept())
  await page.addInitScript(
    ({ role, lang }) => {
      localStorage.setItem("access_token", "identity-token")
      localStorage.setItem("esa:role", role)
      localStorage.setItem("esa:lang", lang)
      if (role === "student")
        localStorage.setItem(
          "esa:student:COACH",
          JSON.stringify({
            id: "alice",
            user_id: "alice-user",
            display_name: "Alice",
          }),
        )
    },
    { role, lang },
  )
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    let json: unknown = []
    if (path.endsWith("/users/me"))
      json = {
        id: role === "student" ? "alice-user" : "teacher",
        role,
        is_active: true,
      }
    else if (path.endsWith("/composer-draft")) json = null
    else if (path.endsWith("/composer-selection"))
      json = {
        passages: [],
        sentences: [],
        scenarios: [],
        instructions: [],
        missing_ids: [],
      }
    else if (
      path.endsWith("/admin/passages") ||
      path.endsWith("/admin/scenarios")
    )
      json = { data: [], count: 0 }
    else if (path.endsWith("/exercises")) json = [exercise]
    else if (path.endsWith("/followup-items")) json = state.sourceItems
    else if (path.endsWith("/diagnostics"))
      json = { checked_at: new Date().toISOString(), issues: [] }
    else if (path.endsWith("/weak-spots"))
      json = { word_gaps: [], low_items: [] }
    else if (path.endsWith("/board"))
      json = {
        classroom_code: "COACH",
        classroom_name: "Speaking class",
        class_size: 2,
        submitted_count: 1,
        completed_count: 1,
        pending_count: 0,
        current_exercise: exercise,
        assigned_items: [],
        engine: "mock",
        items: [{ item_id: item.id, type: "passage", status: "missing" }],
        students: ["Alice", "Ben"].map((name, index) => ({
          student_id: name.toLowerCase(),
          display_name: name,
          done_count: index ? 0 : 1,
          total_count: 1,
          has_pending: false,
          round_status: index ? "not_started" : "all_done",
          items: [
            {
              item_id: item.id,
              type: "passage",
              status: index ? "missing" : "done",
              attempt_id: index ? null : "answer",
              overall: index ? null : 88,
            },
          ],
        })),
      }
    else if (path.endsWith("/teacher-feedback")) {
      if (state.fail)
        return route.fulfill({ status: 503, json: { detail: "Unavailable" } })
      if (state.conflict)
        return route.fulfill({
          status: 409,
          json: { detail: "Teacher feedback revision conflict" },
        })
      const body = route.request().postDataJSON() as {
        text: string
        focus: boolean
        expected_revision: number
      }
      expect(body.expected_revision).toBe(
        state.attempt.teacher_feedback_revision,
      )
      state.attempt = {
        ...state.attempt,
        teacher_feedback: body.text,
        teacher_focus: body.focus,
        teacher_feedback_revision: body.expected_revision + 1,
        teacher_feedback_author: "Ms Lee",
        teacher_feedback_at: new Date().toISOString(),
      }
      json = state.attempt
    } else if (path.endsWith("/attempts/answer")) json = state.attempt
    else if (path.endsWith("/followups")) {
      if (route.request().method() === "POST") {
        if (state.fail)
          return route.fulfill({ status: 503, json: { detail: "Unavailable" } })
        const body = route.request().postDataJSON() as {
          student_ids: string[]
          item_ids: string[]
          title: string
        }
        state.bodies.push(body)
        state.tasks.push({
          id: "task",
          title: body.title,
          status: "followup",
          source_exercise_id: exercise.id,
          created_at: new Date().toISOString(),
          item_count: body.item_ids.length,
          targets: body.student_ids.map((id) => ({
            student_id: id,
            display_name: id === "alice" ? "Alice" : "Ben",
            done_count: 0,
            total_count: body.item_ids.length,
            has_pending: false,
            has_failures: false,
            session_id: null,
          })),
        })
        json = { id: "task" }
      } else {
        const status = url.searchParams.get("status") ?? "all"
        const offset = Number(url.searchParams.get("offset") ?? 0)
        const limit = Number(url.searchParams.get("limit") ?? 50)
        state.followupRequests.push({ status, offset, limit })
        if (state.failList)
          return route.fulfill({ status: 503, json: { detail: "Unavailable" } })
        const visible =
          role === "teacher"
            ? state.tasks
            : state.tasks
                .map((task) => ({
                  ...task,
                  targets: task.targets.filter(
                    (row) => row.student_id === "alice",
                  ),
                }))
                .filter((task) => task.targets.length > 0)
        json = visible
          .filter((task) => {
            const active =
              task.status === "followup" &&
              task.targets.some((row) => row.done_count < row.total_count)
            return status === "all" || (status === "active" ? active : !active)
          })
          .sort(
            (a, b) =>
              (b.created_at ?? "").localeCompare(a.created_at ?? "") ||
              b.id.localeCompare(a.id),
          )
          .slice(offset, offset + limit)
      }
    } else if (path.endsWith("/followups/task/start")) {
      state.started++
      json = { session_id: "followup-session" }
    } else if (/\/followups\/[^/]+\/cancel$/.test(path)) {
      const parts = path.split("/")
      const task = state.tasks.find((row) => row.id === parts[parts.length - 2])
      if (task) task.status = "followup_closed"
      json = null
    } else if (path.endsWith("/revision")) json = { revision: "v1" }
    else if (path.endsWith("/today")) {
      const followup = url.searchParams.get("session_id") === "followup-session"
      json = {
        session_id: followup ? "followup-session" : "original-session",
        classroom_code: "COACH",
        band: "B1",
        items: [item],
        attempts: followup
          ? []
          : [{ ...state.attempt, item_id: item.id, attempt_id: "answer" }],
        assigned_unit_title: followup ? "Targeted practice" : exercise.title,
        exam: null,
        questions_exhausted: true,
        gamification: { xp: 12, streak_days: 1, badges: [], session_stars: 1 },
      }
    } else if (path.endsWith("/path"))
      json = { classroom_code: "COACH", unlock_all: false, units: [] }
    else if (path.endsWith("/trail"))
      json = {
        classroom_code: "COACH",
        student_id: "alice",
        display_name: "Alice",
        sessions: [],
      }
    await route.fulfill({ json })
  })
  return state
}

for (const [width, lang] of [
  [390, "zh"],
  [820, "en"],
  [1180, "zh"],
] as const) {
  test(`@webkit teacher saves feedback and assigns only selected student at ${width} ${lang}`, async ({
    page,
  }) => {
    const en = lang === "en"
    await page.setViewportSize({ width, height: 1000 })
    const state = await setup(page, "teacher", lang)
    await page.goto("/t/COACH")
    await page
      .getByRole("tab", { name: en ? "Student Results" : "学生结果" })
      .click()
    await page
      .getByRole("button", {
        name: en ? "Expand details for Alice" : "展开 Alice 的详情",
      })
      .click()
    await page
      .getByRole("button", {
        name: en ? "Review & comment" : "查看与点评",
        exact: true,
      })
      .click()
    let dialog = page.getByRole("dialog")
    await dialog
      .getByRole("textbox", {
        name: en ? "Teacher feedback text" : "教师点评内容",
      })
      .fill("Use a clear opening and add one detail.")
    await dialog
      .getByRole("checkbox", {
        name: en ? "Mark as a focus area" : "标记为重点关注",
      })
      .check()
    await dialog
      .getByRole("button", {
        name: en ? "Save teacher feedback" : "保存教师点评",
      })
      .click()
    await expect(
      dialog.getByRole("region", {
        name: en ? "Teacher feedback" : "教师点评",
        exact: true,
      }),
    ).toContainText("Use a clear opening")
    expect(state.attempt.teacher_focus).toBe(true)
    expect(state.attempt.overall).toBe(88)
    await page.keyboard.press("Escape")
    const tasks = page.getByRole("region", {
      name: en ? "Targeted practice" : "指定学生补练",
      exact: true,
    })
    await tasks
      .getByRole("button", {
        name: en ? "Assign targeted practice" : "布置补练",
        exact: true,
      })
      .click()
    dialog = page.getByRole("dialog")
    await dialog.getByRole("checkbox", { name: "Alice", exact: true }).check()
    await dialog
      .getByRole("button", {
        name: en ? "Assign to 1 student" : "确认布置给 1 人",
        exact: true,
      })
      .click()
    await expect.poll(() => state.bodies.length).toBe(1)
    expect(state.bodies[0].student_ids).toEqual(["alice"])
    expect(state.bodies[0].item_ids).toEqual([item.id])
    await expect(tasks).toContainText(en ? "0/1 completed" : "0/1 人完成")
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
  })
}

test("@webkit feedback save failure keeps text and revision conflict requires explicit reload", async ({
  page,
}) => {
  const state = await setup(page, "teacher")
  await page.goto("/t/COACH")
  await page.getByRole("tab", { name: "学生结果" }).click()
  await page.getByRole("button", { name: "展开 Alice 的详情" }).click()
  await page.getByRole("button", { name: "查看与点评", exact: true }).click()
  const dialog = page.getByRole("dialog")
  const input = dialog.getByRole("textbox", { name: "教师点评内容" })
  state.fail = true
  await input.fill("My unsaved comment")
  await dialog.getByRole("button", { name: "保存教师点评" }).click()
  await expect(
    dialog.getByRole("alert").filter({ hasText: "保存失败" }),
  ).toBeVisible()
  await expect(input).toHaveValue("My unsaved comment")
  state.fail = false
  state.conflict = true
  state.attempt = {
    ...state.attempt,
    teacher_feedback_revision: 4,
    teacher_feedback: "Other page comment",
  }
  await dialog.getByRole("button", { name: "保存教师点评" }).click()
  await expect(
    dialog.getByRole("alert").filter({ hasText: "点评已被其他页面修改" }),
  ).toBeVisible()
  await expect(input).toHaveValue("My unsaved comment")
  await dialog.getByRole("button", { name: "重新加载点评" }).click()
  await expect(input).toHaveValue("Other page comment")
})

for (const [width, lang] of [
  [390, "zh"],
  [820, "en"],
  [1180, "zh"],
] as const) {
  test(`@webkit student sees teacher feedback and starts independent task at ${width} ${lang}`, async ({
    page,
  }) => {
    const en = lang === "en"
    await page.setViewportSize({ width, height: 1000 })
    const state = await setup(page, "student", lang)
    state.attempt.teacher_feedback = "Practise a clear opening."
    state.attempt.teacher_focus = true
    state.tasks = [
      {
        id: "task",
        title: "My focused practice",
        status: "followup",
        source_exercise_id: exercise.id,
        created_at: new Date().toISOString(),
        item_count: 1,
        targets: [
          {
            student_id: "alice",
            display_name: "Alice",
            done_count: 0,
            total_count: 1,
            has_pending: false,
            has_failures: false,
            session_id: null,
          },
        ],
      },
    ]
    await page.goto("/p/COACH/result?session=original-session")
    await expect(
      page.getByRole("region", {
        name: en ? "Teacher feedback" : "教师点评",
        exact: true,
      }),
    ).toContainText("Practise a clear opening.")
    await page.goto("/home/COACH")
    const tasks = page.getByRole("region", {
      name: en ? "Practice from your teacher" : "老师布置的补练",
      exact: true,
    })
    await expect(tasks).toContainText("My focused practice")
    await tasks
      .getByRole("button", {
        name: en ? "Start practice" : "开始补练",
        exact: true,
      })
      .click()
    await expect(page).toHaveURL(/\/p\/COACH.*session=followup-session/)
    expect(state.started).toBe(1)
    await expect(
      page.getByText(item.text, { exact: true }).first(),
    ).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
  })
}

function pagedTask(
  index: number,
  kind: "active" | "done" | "withdrawn",
): FollowupPublic {
  const id = `${kind}-${String(index).padStart(3, "0")}`
  return {
    id,
    title: id,
    status: kind === "withdrawn" ? "followup_closed" : "followup",
    source_exercise_id: exercise.id,
    // Active work is deliberately older than more than 50 historical tasks.
    created_at:
      kind === "active" ? "2026-01-01T00:00:00Z" : "2026-10-01T00:00:00Z",
    item_count: 1,
    targets: [
      {
        student_id: "alice",
        display_name: "Alice",
        done_count: kind === "done" ? 1 : 0,
        total_count: 1,
        has_pending: false,
        has_failures: false,
        session_id: kind === "done" ? "followup-session" : null,
      },
    ],
  }
}

async function openTaskList(
  page: Page,
  role: "teacher" | "student",
  en = false,
) {
  await page.goto(role === "teacher" ? "/t/COACH" : "/home/COACH")
  if (role === "teacher")
    await page
      .getByRole("tab", { name: en ? "Student Results" : "学生结果" })
      .click()
  const tasks = page.getByRole("region", {
    name:
      role === "teacher"
        ? en
          ? "Targeted practice"
          : "指定学生补练"
        : en
          ? "Practice from your teacher"
          : "老师布置的补练",
    exact: true,
  })
  if (role === "teacher")
    await tasks
      .getByText(
        en ? "View tasks, progress and outcomes" : "查看任务、进度与补练效果",
        { exact: true },
      )
      .click()
  return tasks
}

for (const role of ["teacher", "student"] as const) {
  for (const [width, lang] of [
    [390, "zh"],
    [820, "en"],
    [1180, "zh"],
  ] as const) {
    test(`@webkit ${role} follow-up tabs page beyond 50 history tasks at ${width} ${lang}`, async ({
      page,
    }) => {
      const en = lang === "en"
      await page.setViewportSize({ width, height: 1000 })
      const state = await setup(page, role, lang)
      state.tasks = [
        ...Array.from({ length: 12 }, (_, index) => pagedTask(index, "active")),
        ...Array.from({ length: 65 }, (_, index) =>
          pagedTask(index, index % 2 ? "done" : "withdrawn"),
        ),
      ]
      const tasks = await openTaskList(page, role, en)
      const previous = tasks.getByRole("button", {
        name: en ? "Previous" : "上一页",
        exact: true,
      })
      const next = tasks.getByRole("button", {
        name: en ? "Next" : "下一页",
        exact: true,
      })
      await expect(
        tasks.getByRole("tab", { name: en ? "To do" : "待完成", exact: true }),
      ).toHaveAttribute("aria-selected", "true")
      await expect(tasks.locator("article")).toHaveCount(10)
      await expect(tasks).toContainText("active-011")
      await expect(tasks).not.toContainText("withdrawn-")
      await expect(previous).toBeDisabled()
      await next.click()
      await expect(tasks.locator("article")).toHaveCount(2)
      await expect(tasks).toContainText("active-000")
      await expect(next).toBeDisabled()
      await tasks
        .getByRole("tab", { name: en ? "History" : "历史", exact: true })
        .click()
      await expect(previous).toBeDisabled()
      await expect(tasks.locator("article")).toHaveCount(10)
      await expect(tasks).not.toContainText("active-")
      for (let number = 2; number <= 7; number++) {
        await next.click()
        await expect(
          tasks.getByText(en ? `Page ${number}` : `第 ${number} 页`, {
            exact: true,
          }),
        ).toBeVisible()
        await expect(tasks.locator("article")).toHaveCount(
          number === 7 ? 5 : 10,
        )
      }
      await expect(next).toBeDisabled()
      await previous.click()
      await expect(tasks.locator("article")).toHaveCount(10)
      await tasks
        .getByRole("tab", { name: en ? "To do" : "待完成", exact: true })
        .click()
      await expect(tasks).toContainText("active-011")
      await expect(previous).toBeDisabled()
      expect(state.followupRequests).toContainEqual({
        status: "active",
        offset: 10,
        limit: 11,
      })
      expect(state.followupRequests).toContainEqual({
        status: "history",
        offset: 60,
        limit: 11,
      })
      expect(
        state.followupRequests.every((request) => request.limit === 11),
      ).toBe(true)
      for (const control of await tasks.locator("button").all()) {
        const box = await control.boundingBox()
        expect(box?.height).toBeGreaterThanOrEqual(44)
      }
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true)
    })
  }

  test(`${role} follow-up scoring polls move completed work to accessible history`, async ({
    page,
  }) => {
    await page.clock.install()
    const state = await setup(page, role)
    const task = pagedTask(0, "active")
    task.targets[0].session_id = "followup-session"
    task.targets[0].has_pending = true
    state.tasks = [task]
    const tasks = await openTaskList(page, role)
    await expect(tasks).toContainText("评分中")
    task.targets[0].has_pending = false
    task.targets[0].has_failures = true
    const interval = role === "teacher" ? 10000 : 20000
    await page.clock.fastForward(interval + 100)
    await expect(tasks).toContainText("评分失败")
    expect(state.followupRequests.length).toBeGreaterThanOrEqual(2)
    task.targets[0].has_failures = false
    task.targets[0].done_count = 1
    await page.clock.fastForward(interval + 100)
    await expect(tasks).toContainText("暂无待完成补练")
    await tasks
      .getByRole("tab", { name: "历史", exact: true })
      .or(tasks.getByRole("button", { name: "查看补练历史", exact: true }))
      .click()
    await expect(tasks).toContainText(task.title)
    if (role === "student") {
      await tasks.getByRole("button", { name: "回看补练", exact: true }).click()
      await expect(page).toHaveURL(
        /\/p\/COACH\/result\?session=followup-session/,
      )
    }
  })
}

test("teacher withdrawal on the final page returns to the previous page", async ({
  page,
}) => {
  const state = await setup(page, "teacher")
  state.tasks = Array.from({ length: 11 }, (_, index) =>
    pagedTask(index, "active"),
  )
  const tasks = await openTaskList(page, "teacher")
  await expect(tasks.locator("article")).toHaveCount(10)
  await tasks.getByRole("button", { name: "下一页", exact: true }).click()
  await expect(tasks.locator("article")).toHaveCount(1)
  await tasks.getByRole("button", { name: "撤销补练", exact: true }).click()
  await expect(tasks.locator("article")).toHaveCount(10)
  await expect(
    tasks.getByRole("button", { name: "上一页", exact: true }),
  ).toBeDisabled()
  await tasks
    .getByRole("tab", { name: "历史", exact: true })
    .or(tasks.getByRole("button", { name: "查看补练历史", exact: true }))
    .click()
  await expect(tasks.locator("article")).toHaveCount(1)
  await expect(tasks).toContainText("已撤销")
})

test("student with only history can reach it from the empty default tab", async ({
  page,
}) => {
  const state = await setup(page, "student")
  state.tasks = [pagedTask(0, "done"), pagedTask(1, "withdrawn")]
  const tasks = await openTaskList(page, "student")
  await expect(tasks).toContainText("暂无待完成补练")
  await tasks
    .getByRole("tab", { name: "历史", exact: true })
    .or(tasks.getByRole("button", { name: "查看补练历史", exact: true }))
    .click()
  await expect(tasks.locator("article")).toHaveCount(2)
  await expect(
    tasks.getByRole("button", { name: "回看补练", exact: true }),
  ).toBeVisible()
  await expect(
    tasks.getByRole("button", { name: "开始补练", exact: true }),
  ).toHaveCount(0)
})

test("follow-up page errors keep tabs and allow retry without losing the page", async ({
  page,
}) => {
  const state = await setup(page, "student")
  state.tasks = Array.from({ length: 12 }, (_, index) =>
    pagedTask(index, "done"),
  )
  const tasks = await openTaskList(page, "student")
  await tasks
    .getByRole("tab", { name: "历史", exact: true })
    .or(tasks.getByRole("button", { name: "查看补练历史", exact: true }))
    .click()
  await expect(tasks.locator("article")).toHaveCount(10)
  state.failList = true
  await tasks.getByRole("button", { name: "下一页", exact: true }).click()
  await expect(
    tasks.getByRole("button", { name: "重试", exact: true }),
  ).toBeVisible({ timeout: 15000 })
  state.failList = false
  await tasks.getByRole("button", { name: "重试", exact: true }).click()
  await expect(tasks.locator("article")).toHaveCount(2)
  await expect(tasks).toContainText("第 2 页")
})

test("assigning from a student item preselects only that student and item", async ({
  page,
}) => {
  const state = await setup(page, "teacher")
  state.sourceItems.push({
    ...item,
    id: "other-item",
    text: "Another source question.",
  })
  await page.goto("/t/COACH")
  await page.getByRole("tab", { name: "学生结果" }).click()
  await page.getByRole("button", { name: "展开 Alice 的详情" }).click()
  await page.getByRole("button", { name: "补练这题", exact: true }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByRole("checkbox", { name: /Alice/ })).toBeChecked()
  await expect(dialog.getByRole("checkbox", { name: /Ben/ })).not.toBeChecked()
  await expect(
    dialog.getByRole("checkbox", { name: /Original frozen/ }),
  ).toBeChecked()
  await expect(
    dialog.getByRole("checkbox", { name: /Another source/ }),
  ).not.toBeChecked()
  expect(state.bodies).toHaveLength(0)
  await dialog.getByRole("button", { name: "确认布置给 1 人" }).click()
  await expect.poll(() => state.bodies.length).toBe(1)
  expect(state.bodies[0]).toMatchObject({
    student_ids: ["alice"],
    item_ids: ["item"],
  })
})
