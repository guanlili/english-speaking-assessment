import { expect, test } from "@playwright/test"

for (const width of [390, 820, 1180]) {
  test(`@webkit composer retains selections across pages and search at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.addInitScript(() => {
      localStorage.setItem("access_token", "teacher-token")
      localStorage.setItem("esa:role", "teacher")
    })
    const articles = Array.from({ length: 81 }, (_, i) => ({
      id: `article-${i}`,
      slug: `article-${i}`,
      title: `Article ${i}`,
      topic: "Paging",
      text: `Detailed passage ${i}.`,
      cefr_band: "B1",
      suggested_seconds: 10,
      is_active: true,
      sentences: [],
      reading_split: false,
      reading_segments: [],
      reading_child_ids: [],
    }))
    const exercise = {
      id: "original",
      title: "Paged practice",
      item_count: 1,
      is_exam: false,
      version_no: 1,
      status: "published",
    }
    const submissions: { items: { type: string; id: string }[] }[] = []
    const reads: URL[] = []
    await page.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname
      let json: unknown = []
      if (path.endsWith("/users/me"))
        json = {
          id: "teacher",
          role: "teacher",
          email: "teacher@example.com",
          is_active: true,
          is_superuser: true,
        }
      else if (path.endsWith("/PAGE/board"))
        json = {
          classroom_code: "PAGE",
          classroom_name: "Paging class",
          class_size: 10,
          submitted_count: 0,
          completed_count: 0,
          pending_count: 0,
          engine: "mock",
          students: [],
          items: [],
          current_exercise: exercise,
          assigned_items: [{ type: "passage", id: "article-0" }],
        }
      else if (path.endsWith("/admin/passages")) {
        reads.push(url)
        const skip = Number(url.searchParams.get("skip") ?? "0")
        const limit = Number(url.searchParams.get("limit"))
        expect(limit).toBe(21)
        const q = url.searchParams.get("q")?.toLowerCase() ?? ""
        const matching = articles.filter((article) =>
          article.title.toLowerCase().includes(q),
        )
        json = {
          data: matching.slice(skip, skip + limit),
          count: matching.length,
        }
      } else if (path.endsWith("/composer-selection")) {
        const body = route.request().postDataJSON() as {
          items: { id: string }[]
        }
        json = {
          passages: articles.filter((article) =>
            body.items.some((item) => item.id === article.id),
          ),
          sentences: [],
          scenarios: [],
          instructions: [],
          missing_ids: [],
        }
      } else if (path.endsWith("/admin/scenarios"))
        json = { data: [], count: 0 }
      else if (path.endsWith("/PAGE/exercises")) json = [exercise]
      else if (path.endsWith("/PAGE/assignment")) {
        submissions.push(route.request().postDataJSON())
        json = exercise
      }
      await route.fulfill({ json })
    })
    await page.goto("/t/PAGE")
    const controls = page.getByRole("group", {
      name: "搜索朗读篇目",
      exact: true,
    })
    await expect(page.locator("#pick-passage-article-0")).toBeChecked()
    await controls.getByRole("button", { name: "下一页" }).click()
    await page.locator("#pick-passage-article-20").check()
    await controls.getByRole("textbox").fill("Article 70")
    await page.locator("#pick-passage-article-70").check()
    await controls.getByRole("textbox").fill("")
    await expect(page.locator("#pick-passage-article-0")).toBeChecked()
    await page.getByRole("button", { name: "预览练习", exact: true }).click()
    const dialog = page.getByRole("dialog")
    await expect(
      dialog.getByText("Article 20", { exact: false }).first(),
    ).toBeVisible()
    await expect(
      dialog.getByText("Article 70", { exact: false }).first(),
    ).toBeVisible()
    await dialog
      .getByRole("button", { name: "确认发布到课堂", exact: true })
      .click()
    await expect.poll(() => submissions.length).toBe(1)
    expect(new Set(submissions[0].items.map((item) => item.id))).toEqual(
      new Set(["article-0", "article-20", "article-70"]),
    )
    expect(reads.some((url) => url.searchParams.get("skip") === "20")).toBe(
      true,
    )
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1)
  })
}
