import { expect, type Page, test } from "@playwright/test"

/** Task-focused student home; all APIs are mocked. */

const CODE = "HOME"

async function mockHome(page: Page) {
  const state = {
    revision: "v1",
    title: "Unit 1 Travel",
    todayReads: 0,
    attempts: [] as { item_id: string; status: string }[],
    exam: null as { started: boolean; ended: boolean } | null,
  }
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token")
    localStorage.setItem("esa:role", "student")
    localStorage.setItem(
      "esa:student:HOME",
      JSON.stringify({
        id: "student",
        display_name: "Student",
        suffix: null,
        user_id: "user",
      }),
    )
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
    } else if (path.endsWith("/revision")) {
      body = { revision: state.revision }
    } else if (path.endsWith("/today")) {
      state.todayReads += 1
      body = {
        session_id: "home-session",
        classroom_code: CODE,
        band: "B1",
        items: [
          {
            type: "passage",
            id: "00000000-0000-4000-8000-000000000001",
            text: "A short passage for the home page.",
            suggested_seconds: 60,
          },
          {
            type: "question",
            id: "00000000-0000-4000-8000-000000000002",
            text: "What is your favorite season?",
            suggested_seconds: 60,
          },
        ],
        attempts: state.attempts,
        exam: state.exam,
        gamification: { xp: 12, streak_days: 3 },
        assigned_unit_title: state.title,
      }
    } else if (path.endsWith("/path")) {
      body = { classroom_code: CODE, unlock_all: false, units: [] }
    } else if (path.endsWith("/trail")) {
      body = {
        classroom_code: CODE,
        student_id: "student",
        display_name: "Student",
        suffix: null,
        sessions: [
          {
            date: new Date().toISOString(),
            attempt_count: 2,
            speaking_avg: 80,
          },
        ],
      }
    }
    await route.fulfill({ json: body })
  })
  return state
}

test("home shows one task summary and opens practice", async ({ page }) => {
  await mockHome(page)
  await page.goto(`/home/${CODE}`)

  // hero：问候 + 今日单元 + CTA
  await expect(page.getByRole("heading", { name: /Hi，Student/ })).toBeVisible()
  await expect(page.getByText("Hi，Student。")).toBeVisible()
  await expect(page.getByText("今日练习 · Unit 1 Travel")).toBeVisible()
  await expect(page.getByRole("button", { name: /开始今日练习/ })).toBeVisible()

  // 今日计划摘要与完成度
  await expect(page.getByText("1 篇朗读 + 1 道情景问答")).toBeVisible()
  await expect(page.getByText("0 / 2 已完成")).toBeVisible()

  await expect(page.getByText("本周开口目标")).toHaveCount(0)
  await expect(page.getByText("给今天的你", { exact: true })).toHaveCount(0)
  await expect(
    page.getByRole("link", { name: "自主练习", exact: true }),
  ).toHaveCount(0)

  // CTA 跳转练习页
  await page.getByRole("button", { name: /开始今日练习/ }).click()
  await expect(page).toHaveURL(new RegExp(`/p/${CODE}`))
})

for (const width of [390, 820, 1180]) {
  for (const lang of ["zh", "en"]) {
    test(`@webkit task navigation fits ${width}px in ${lang}`, async ({
      page,
    }) => {
      await mockHome(page)
      await page.addInitScript(
        (value) => localStorage.setItem("esa:lang", value),
        lang,
      )
      await page.setViewportSize({ width, height: 900 })
      await page.goto(`/home/${CODE}`)
      await expect(
        page.getByRole("button", {
          name: lang === "zh" ? "开始今日练习" : "Start today's practice",
        }),
      ).toBeVisible()
      const navigation = page.getByRole("navigation", {
        name:
          lang === "zh"
            ? width < 768
              ? "手机学习导航"
              : "学习导航"
            : width < 768
              ? "Mobile learning navigation"
              : "Learning navigation",
        exact: true,
      })
      await expect(
        navigation.getByRole("link", {
          name: lang === "zh" ? "今日任务" : "Today’s Tasks",
          exact: true,
        }),
      ).toBeVisible()
      await expect(
        navigation.getByRole("link", {
          name: lang === "zh" ? "今日练习" : "Today's Practice",
          exact: true,
        }),
      ).toHaveCount(0)
      if (width < 768) await expect(navigation.getByRole("link")).toHaveCount(3)
      expect(
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      ).toBeLessThanOrEqual(1)
      await page.screenshot({
        path: `/tmp/student-tasks-${width}-${lang}.png`,
        fullPage: true,
      })
    })
  }
}

test("failed latest answer does not complete a task or unlock self practice", async ({
  page,
}) => {
  const state = await mockHome(page)
  state.attempts = [
    { item_id: "00000000-0000-4000-8000-000000000001", status: "done" },
    { item_id: "00000000-0000-4000-8000-000000000001", status: "failed" },
    { item_id: "00000000-0000-4000-8000-000000000002", status: "done" },
  ]
  await page.goto(`/home/${CODE}`)
  await expect(page.getByText("1 / 2 已完成")).toBeVisible()
  await expect(page.getByRole("button", { name: "继续今日练习" })).toBeVisible()
  await expect(
    page.getByRole("link", { name: "自主练习", exact: true }),
  ).toHaveCount(0)
})

test("completed practice offers results and optional self practice", async ({
  page,
}) => {
  const state = await mockHome(page)
  state.attempts = [
    { item_id: "00000000-0000-4000-8000-000000000001", status: "done" },
    { item_id: "00000000-0000-4000-8000-000000000002", status: "done" },
  ]
  await page.goto(`/home/${CODE}`)
  await expect(page.getByText("2 / 2 已完成")).toBeVisible()
  await expect(page.getByRole("button", { name: "查看今日成果" })).toBeVisible()
  await page.getByRole("link", { name: "自主练习", exact: true }).click()
  await expect(page).toHaveURL(`/explore/${CODE}`)
})

test("an active exam keeps the exam entry and hides the optional self practice action", async ({
  page,
}) => {
  const state = await mockHome(page)
  state.exam = { started: true, ended: false }
  await page.goto(`/home/${CODE}`)
  await expect(page.getByRole("button", { name: "继续考试" })).toBeVisible()
  await expect(
    page.getByRole("link", { name: "自主练习", exact: true }),
  ).toHaveCount(0)
})

test("home sees a new publication and unchanged revisions do not reload the plan", async ({
  page,
}) => {
  const state = await mockHome(page)
  await page.goto(`/home/${CODE}`)
  await expect(page.getByText("今日练习 · Unit 1 Travel")).toBeVisible()
  state.title = "Unit 2 Stories"
  state.revision = "v2"
  await expect(page.getByText("今日练习 · Unit 2 Stories")).toBeVisible({
    timeout: 8000,
  })
  const loaded = state.todayReads
  await page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/revision"),
  )
  expect(state.todayReads).toBe(loaded)
})
