import { expect, test } from "@playwright/test"

for (const width of [390, 820, 1180]) {
  for (const lang of ["zh", "en"]) {
    test(`@webkit repeat library searches and pages at ${width}px in ${lang}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 })
      await page.addInitScript((language) => {
        localStorage.setItem("access_token", "teacher-token")
        localStorage.setItem("esa:role", "teacher")
        localStorage.setItem("esa:lang", language)
      }, lang)
      const searches: string[] = []
      await page.route("**/api/v1/**", async (route) => {
        const url = new URL(route.request().url())
        const path = url.pathname
        if (path.endsWith("/users/me"))
          return route.fulfill({
            json: {
              id: "teacher",
              email: "teacher@example.com",
              role: "teacher",
              is_active: true,
            },
          })
        if (path.endsWith("/sentences-page")) {
          expect(url.searchParams.get("limit")).toBe("20")
          expect(url.searchParams.get("standalone_only")).toBe("true")
          const q = url.searchParams.get("q") ?? ""
          const skip = Number(url.searchParams.get("skip") ?? "0")
          if (q) searches.push(q)
          const count = q ? 1 : 45
          const data = Array.from(
            { length: Math.max(0, Math.min(20, count - skip)) },
            (_, i) => ({
              id: `sentence-${skip + i}`,
              text: q ? "Unique search result" : `Sentence ${skip + i}`,
              order_index: skip + i,
              suggested_seconds: 8,
              replay_limit: 3,
              passage_id: null,
              passage_title: null,
              exam_kind: null,
              exam_level: null,
              audio_url: null,
              exam_settings: null,
            }),
          )
          return route.fulfill({ json: { data, count } })
        }
        if (/\/(passages|scenarios|questions)$/.test(path))
          return route.fulfill({ json: { data: [], count: 0 } })
        return route.fulfill({ json: [] })
      })
      await page.goto("/create#bank-repeat")
      const section = page.locator("#bank-repeat")
      const pager = section.getByRole("navigation", {
        name: lang === "en" ? "Pagination" : "分页",
      })
      const next = pager.getByRole("button", {
        name: lang === "en" ? "Next" : "下一页",
      })
      await expect(
        section.getByText("Sentence 0", { exact: true }),
      ).toBeVisible()
      await next.click()
      await expect(
        section.getByText("Sentence 20", { exact: true }),
      ).toBeVisible()
      await expect(
        section.getByText("Sentence 0", { exact: true }),
      ).toHaveCount(0)
      await next.click()
      await expect(
        section.getByText("Sentence 44", { exact: true }),
      ).toBeVisible()
      await expect(next).toBeDisabled()
      const search = section.getByRole("textbox", {
        name: lang === "en" ? "Search repeat sentences" : "搜索复述句",
      })
      await search.pressSequentially("unique", { delay: 20 })
      await expect(
        section.getByText("Unique search result", { exact: true }),
      ).toBeVisible()
      expect(searches).toEqual(["unique"])
      await expect(pager).toHaveCount(0)
      expect(
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      ).toBeLessThanOrEqual(1)
      expect(
        await search.evaluate((element) =>
          Number.parseFloat(getComputedStyle(element).fontSize),
        ),
      ).toBeGreaterThanOrEqual(16)
    })
  }
}
