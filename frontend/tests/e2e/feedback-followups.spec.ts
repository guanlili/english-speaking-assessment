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
    tasks: [] as FollowupPublic[],
    bodies: [] as { student_ids: string[]; item_ids: string[] }[],
    fail: false,
    conflict: false,
    started: 0,
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
    else if (path.endsWith("/followup-items")) json = [item]
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
      } else
        json =
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
    } else if (path.endsWith("/followups/task/start")) {
      state.started++
      json = { session_id: "followup-session" }
    } else if (path.endsWith("/followups/task/cancel")) {
      state.tasks[0].status = "followup_closed"
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
        name: en ? "Detailed Feedback" : "详细反馈",
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
  await page.getByRole("button", { name: "详细反馈", exact: true }).click()
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
