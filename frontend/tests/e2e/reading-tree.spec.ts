import { expect, type Page, test } from "@playwright/test"

const article = {
  id: "00000000-0000-4000-8000-000000000001",
  slug: "article",
  title: "Our school article",
  topic: "School",
  text: "We study together. We help our friends!",
  cefr_band: "B1",
  suggested_seconds: 45,
  is_active: true,
  reading_split: true,
  reading_segments: ["We study together.", "We help our friends!"],
  sentences: [],
}

async function mockBank(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token")
    localStorage.setItem("esa:role", "teacher")
  })
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith("/users/me"))
      body = {
        id: "teacher",
        email: "teacher@example.com",
        role: "teacher",
        is_active: true,
        is_superuser: true,
      }
    else if (path.endsWith("/admin/passages")) body = [article]
    else if (path.endsWith("/classes/TREE/board"))
      body = {
        classroom_code: "TREE",
        classroom_name: "Tree test",
        class_size: 10,
        submitted_count: 0,
        pending_count: 0,
        engine: "mock",
        students: [],
      }
    await route.fulfill({ json: body })
  })
}

async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1)
}

for (const width of [390, 820, 1180]) {
  test(`article tree and whole-article selection at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    await mockBank(page)
    await page.goto("/create")
    const card = page.getByTestId(`passage-${article.id}`)
    await expect(card).toBeVisible()
    await expect(card.getByTestId("reading-sentences")).toHaveCount(0)
    await card.getByRole("button", { name: article.title, exact: true }).click()
    await expect(
      card.getByTestId("reading-sentences").getByRole("listitem"),
    ).toHaveCount(2)
    await noOverflow(page)
    await card.getByRole("button", { name: article.title, exact: true }).click()
    await expect(card.getByTestId("reading-sentences")).toHaveCount(0)

    await page.goto("/t/TREE")
    await page.getByText("文章朗读", { exact: true }).click()
    const picker = page.getByTestId(`pick-article-${article.id}`)
    await expect(picker).toBeVisible()
    // 拆分文章的选题卡标出逐句题数；勾选仍是整篇一个入口
    await expect(picker.getByText("逐句 2 题")).toBeVisible()
    await picker.getByRole("button", { name: "查看内容" }).click()
    await expect(picker.getByRole("listitem")).toHaveCount(2)
    await expect(picker.getByRole("checkbox")).toHaveCount(1)
    await expect(picker.getByRole("checkbox")).not.toBeChecked()
    await picker.getByText(article.title, { exact: true }).click()
    await expect(picker.getByRole("checkbox")).toBeChecked()
    await expect(page.getByText("朗读 1 篇 · 逐句 2 题")).toBeVisible()
    await noOverflow(page)
  })
}
