import { expect, type Page, test } from "@playwright/test"
import type { ComposerState, DraftPublic } from "../../src/client"

const article = {
  id: "article",
  slug: "article",
  title: "A journey",
  topic: "Travel",
  text: "We visited a new city.",
  cefr_band: "B1",
  suggested_seconds: 10,
  is_active: true,
  sentences: [],
  reading_split: false,
  reading_segments: [],
  reading_child_ids: [],
}
const exercise = {
  id: "published",
  classroom_id: "class",
  title: "Original practice",
  version_no: 1,
  item_count: 1,
  status: "published",
  is_exam: false,
}
const state: ComposerState = {
  title: "Earlier practice",
  types: { reading: true, repeat: false, qa: false, instruction: false },
  selection: {
    passages: [article.id],
    sentences: [],
    scenarioIds: [],
    questions: [],
    instructions: [],
  },
  ordered_keys: ["passage:article"],
  is_exam: false,
  exam_minutes: 30,
  base_exercise_id: "published",
}
async function setup(page: Page, lang = "zh") {
  page.on("dialog", (dialog) => void dialog.accept())
  const drafts: Record<string, DraftPublic | null> = {
    SOURCE: null,
    TARGET: null,
  }
  let conflict = false
  let offline = false
  const published: unknown[] = []
  await page.addInitScript((lang) => {
    localStorage.setItem("access_token", "teacher-token")
    localStorage.setItem("esa:role", "teacher")
    localStorage.setItem("esa:lang", lang)
  }, lang)
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    const code = path.includes("/TARGET/") ? "TARGET" : "SOURCE"
    let json: unknown = []
    if (path.endsWith("/users/me"))
      json = { id: "teacher", role: "teacher", is_active: true }
    else if (path.endsWith("/classes"))
      json = ["SOURCE", "TARGET"].map((code) => ({
        id: code,
        code,
        name: code,
        is_active: true,
        current_exercise_id: exercise.id,
      }))
    else if (path.endsWith("/composer-draft")) {
      if (route.request().method() === "PUT") {
        if (offline) return route.abort("failed")
        const body = route.request().postDataJSON() as {
          expected_revision: number
          state: ComposerState
        }
        if (
          conflict ||
          body.expected_revision !== (drafts[code]?.revision ?? 0)
        )
          return route.fulfill({
            status: 409,
            json: { detail: "Draft revision conflict" },
          })
        drafts[code] = {
          revision: (drafts[code]?.revision ?? 0) + 1,
          state: body.state,
          updated_at: new Date().toISOString(),
        }
      }
      json = drafts[code]
    } else if (path.endsWith("/composer-seed")) json = state
    else if (path.endsWith("/diagnostics"))
      json = {
        checked_at: new Date().toISOString(),
        issues: [
          {
            student_id: "student",
            display_name: "Emma",
            kind: "upload",
            observed_at: new Date().toISOString(),
          },
        ],
      }
    else if (path.endsWith("/board"))
      json = {
        classroom_code: code,
        classroom_name: code,
        class_size: 1,
        submitted_count: 0,
        completed_count: 0,
        pending_count: 0,
        engine: "mock",
        students: [
          {
            student_id: "student",
            display_name: "Emma",
            done_count: 0,
            total_count: 1,
            has_pending: false,
            round_status: "not_started",
            items: [
              { item_id: article.id, type: "passage", status: "missing" },
            ],
          },
        ],
        items: [{ item_id: article.id, type: "passage", status: "missing" }],
        current_exercise: exercise,
        assigned_items: [{ type: "passage", id: article.id }],
      }
    else if (path.endsWith("/admin/passages"))
      json = { data: [article], count: 1 }
    else if (path.endsWith("/composer-selection"))
      json = {
        passages: [article],
        sentences: [],
        scenarios: [],
        instructions: [],
        missing_ids: [],
      }
    else if (path.endsWith("/admin/scenarios")) json = { data: [], count: 0 }
    else if (path.endsWith("/exercises")) json = [exercise]
    else if (path.endsWith("/assignment")) {
      published.push(route.request().postDataJSON())
      drafts[code] = null
      json = null
    }
    await route.fulfill({ json })
  })
  return {
    drafts,
    published,
    conflict: () => {
      conflict = true
    },
    offline: (value: boolean) => {
      offline = value
    },
  }
}

for (const [width, lang] of [
  [390, "zh"],
  [820, "en"],
  [1180, "zh"],
] as const) {
  test(`@webkit saves draft across refresh without publishing at ${width} ${lang}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    const mock = await setup(page, lang)
    await page.goto("/t/SOURCE")
    const input = page.getByPlaceholder(
      lang === "en"
        ? "e.g., Week 3 | Travel-themed speaking"
        : "例如：第 3 周｜旅行主题口语练习",
    )
    await input.fill("My saved preparation")
    await expect
      .poll(() => mock.drafts.SOURCE?.state.title)
      .toBe("My saved preparation")
    expect(mock.published).toHaveLength(0)
    await page.reload()
    await expect(input).toHaveValue("My saved preparation")
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
  })
}

test("@webkit failed save retains edits and retries; conflict prevents overwrite and publish", async ({
  page,
}) => {
  const mock = await setup(page)
  await page.goto("/t/SOURCE")
  const title = page.getByPlaceholder("例如：第 3 周｜旅行主题口语练习")
  mock.offline(true)
  await title.fill("Unsaved edits")
  await expect(
    page.getByText("草稿尚未保存，请重试并保持页面打开。", { exact: true }),
  ).toBeVisible()
  await expect(title).toHaveValue("Unsaved edits")
  mock.offline(false)
  await page.getByRole("button", { name: "重试保存" }).click()
  await expect.poll(() => mock.drafts.SOURCE?.state.title).toBe("Unsaved edits")
  mock.conflict()
  await title.fill("Other device wins")
  await expect(page.getByText(/其他设备已修改草稿/)).toBeVisible()
  expect(mock.drafts.SOURCE?.state.title).toBe("Unsaved edits")
  await page.getByRole("button", { name: "预览练习", exact: true }).click()
  await page
    .getByRole("button", { name: "确认发布到课堂", exact: true })
    .click()
  await expect(page.getByText(/发布失败，草稿已保留/)).toBeVisible()
  expect(mock.published).toHaveLength(0)
})

test("@webkit copies history to another class draft with explicit replacement and no publication", async ({
  page,
}) => {
  const mock = await setup(page)
  mock.drafts.TARGET = {
    state: { ...state, title: "Existing work" },
    revision: 4,
    updated_at: new Date().toISOString(),
  }
  await page.goto("/t/SOURCE")
  await page.getByRole("tab", { name: "发布历史" }).click()
  await page.getByRole("button", { name: "复制练习", exact: true }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByRole("combobox").selectOption("TARGET")
  const copy = dialog.getByRole("button", { name: "复制到草稿", exact: true })
  await expect(copy).toBeDisabled()
  await dialog.getByRole("checkbox").check()
  await copy.click()
  await expect(page).toHaveURL(/\/t\/TARGET/)
  await expect(
    page.getByPlaceholder("例如：第 3 周｜旅行主题口语练习"),
  ).toHaveValue("Earlier practice")
  expect(mock.drafts.TARGET?.revision).toBe(5)
  expect(mock.drafts.SOURCE).toBeNull()
  expect(mock.published).toHaveLength(0)
})

test("@webkit reported issues lead to the affected student", async ({
  page,
}) => {
  await setup(page)
  await page.goto("/t/SOURCE")
  await page.getByRole("tab", { name: "学生结果" }).click()
  const issues = page.getByRole("region", { name: "课堂异常", exact: true })
  await expect(
    issues.getByText("录音提交异常：请在学生设备重试上传"),
  ).toBeVisible()
  await issues.getByRole("link", { name: "定位学生" }).click()
  await expect(page.locator("#student-student")).toHaveAttribute(
    "data-state",
    "selected",
  )
})

test("@webkit restoring current selections clears an outdated draft warning", async ({
  page,
}) => {
  const mock = await setup(page)
  mock.drafts.SOURCE = {
    revision: 3,
    state: {
      ...state,
      title: "Outdated preparation",
      base_exercise_id: "older-publication",
    },
    updated_at: new Date().toISOString(),
  }
  await page.goto("/t/SOURCE")
  await expect(page.getByText(/当前发布已变化，草稿仍保留原选题/)).toBeVisible()
  await page
    .getByRole("button", { name: "恢复当前发布选题", exact: true })
    .click()
  await expect(
    page.getByPlaceholder("例如：第 3 周｜旅行主题口语练习"),
  ).toHaveValue(exercise.title)
  await expect
    .poll(() => mock.drafts.SOURCE?.state.base_exercise_id)
    .toBe(exercise.id)
  await expect(page.getByText(/当前发布已变化，草稿仍保留原选题/)).toHaveCount(
    0,
  )
})
