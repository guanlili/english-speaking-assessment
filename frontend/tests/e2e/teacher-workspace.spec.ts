import { expect, type Page, test } from "@playwright/test"

async function mockWorkspace(page: Page, lang: string) {
  await page.addInitScript((lang) => {
    localStorage.setItem("access_token", "teacher-token")
    localStorage.setItem("esa:role", "teacher")
    localStorage.setItem("esa:lang", lang)
  }, lang)
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith("/users/me"))
      body = { id: "teacher", role: "teacher", is_active: true }
    else if (path.endsWith("/classes"))
      body = [
        {
          id: "class",
          code: "DESIGN",
          name: "七年级 · English Speaking",
          grade: "Grade 7",
          teaching_goal:
            "用具体细节讲述自己的故事。 Share your story with specific details.",
          is_active: true,
          class_size: 40,
        },
        {
          id: "old",
          code: "OLD",
          name: "Archived classroom",
          is_active: false,
          class_size: 20,
        },
      ]
    else if (path.endsWith("/admin/units"))
      body = [
        {
          id: "unit",
          title: "Stories worth sharing",
          topic: "Stories",
          order_index: 1,
          is_active: true,
          passage_count: 1,
        },
      ]
    else if (path.endsWith("/admin/topics")) body = ["Stories"]
    else if (/\/admin\/(scenarios|questions|passages)$/.test(path))
      body = { data: [], count: 0 }
    else if (path.endsWith("/learning-report"))
      body = {
        display_name: "Student",
        start_date: "2026-10-11",
        end_date: "2026-10-17",
        session_count: 0,
        completed_items: 0,
        total_items: 0,
        speaking_minutes: 0,
        reading_avg: null,
        question_avg: null,
        answers: [],
        has_active_exam: false,
      }
    else if (path.endsWith("/exercises")) body = []
    else if (path.endsWith("/trail"))
      body = {
        display_name: "Emma Wilson",
        classroom_code: "DESIGN",
        sessions: [],
      }
    else if (path.endsWith("/sessions"))
      body = [
        {
          session_id: "session",
          session_date: "2026-10-12",
          title: "Stories worth sharing",
          is_exam: false,
          done_count: 2,
          total_count: 3,
          overall_avg: 78,
          attempt_ids: ["answer"],
        },
      ]
    else if (path.endsWith("/board")) body = { students: [], items: [] }
    else if (path.endsWith("/attempts/answer"))
      body = {
        id: "answer",
        item_type: "question",
        status: "done",
        overall: 78,
        engine: "ark",
        item_text: "Tell us your story.",
        advice: ["Add one specific detail."],
      }
    await route.fulfill({ json: body })
  })
}

async function noPageOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
}

for (const width of [390, 820, 1180]) {
  for (const lang of ["zh", "en"]) {
    test(`@webkit teacher workspace navigation and feedback at ${width}px in ${lang}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 })
      await mockWorkspace(page, lang)
      const en = lang === "en"
      await page.goto("/classrooms")
      await expect(
        page.getByText("七年级 · English Speaking", { exact: true }),
      ).toBeVisible()
      await noPageOverflow(page)
      const search = page.getByRole("textbox", {
        name: en ? "Search by classroom name or code" : "搜索课堂名称或课堂码",
      })
      await search.fill("Nobody")
      await expect(
        page.getByText(en ? "No matching classrooms." : "没有匹配的课堂。", {
          exact: true,
        }),
      ).toBeVisible()
      await search.fill("DESIGN")
      const enter = page.getByRole("link", {
        name: en ? "Open Classroom →" : "进入课堂 →",
      })
      await expect(enter).toHaveAttribute("href", "/t/DESIGN")
      expect((await enter.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      await page
        .getByRole("button", {
          name: en ? "New Classroom" : "新建课堂",
          exact: true,
        })
        .click()
      await expect(page.getByRole("dialog")).toBeVisible()
      await noPageOverflow(page)
      await page.keyboard.press("Escape")
      await page.goto("/create?classroom=DESIGN")
      const nav = page.getByRole("navigation", {
        name: en ? "Question bank sections" : "题目库分区",
      })
      await expect(nav).toBeVisible()
      await noPageOverflow(page)
      await nav.getByRole("link", { name: /Scenario Q&A|情景问答/ }).click()
      await expect(page).toHaveURL(/#bank-qa$/)
      await page
        .getByRole("button", {
          name: en ? "Search, edit & bulk entry" : "搜索、编辑与批量录入",
        })
        .click()
      await noPageOverflow(page)
      await nav
        .getByRole("link", { name: /Topics · Units|主题 · 单元/ })
        .click()
      await page
        .getByRole("button", {
          name: en ? "New Topic" : "新建主题",
          exact: true,
        })
        .click()
      await expect(page.getByRole("dialog")).toBeVisible()
      await noPageOverflow(page)
      await page.keyboard.press("Escape")
      await page.goto("/t/DESIGN/s/student")
      await expect(
        page.getByRole("heading", { name: "Emma Wilson", exact: true }),
      ).toBeVisible()
      await expect(
        page.getByText("Stories worth sharing", { exact: false }),
      ).toBeVisible()
      await noPageOverflow(page)
      await page
        .getByRole("button", {
          name: en ? "Answer feedback 1" : "作答反馈 1",
          exact: true,
        })
        .click()
      await expect(
        page.getByRole("dialog").getByText("Add one specific detail."),
      ).toBeVisible()
      await noPageOverflow(page)
    })
  }
}
