import { expect, test } from "@playwright/test"

for (const width of [390, 820, 1180]) {
  test(`teacher loads older sessions and feedback at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.addInitScript(() => {
      localStorage.setItem("access_token", "test-token")
      localStorage.setItem("esa:role", "teacher")
    })
    const offsets: number[] = []
    await page.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url())
      let body: unknown = {}
      if (url.pathname.endsWith("/users/me"))
        body = { id: "teacher", role: "teacher", is_active: true }
      else if (url.pathname.endsWith("/sessions")) {
        const offset = Number(url.searchParams.get("offset"))
        offsets.push(offset)
        body = Array.from({ length: offset === 0 ? 30 : 1 }, (_, i) => ({
          session_id: `session-${offset + i}`,
          session_date: "2026-10-01",
          mode: "daily",
          title: `History round ${offset + i + 1}`,
          is_exam: false,
          exam_ended: false,
          done_count: 1,
          total_count: 1,
          overall_avg: 80,
          attempt_ids: offset === 30 ? ["old-attempt"] : [],
        }))
      } else if (url.pathname.endsWith("/trail"))
        body = {
          display_name: "Student",
          classroom_code: "GENERAL",
          sessions: [],
        }
      else if (url.pathname.endsWith("/board")) body = { students: [] }
      else if (url.pathname.endsWith("/classes")) body = { data: [] }
      else if (url.pathname.endsWith("/attempts/old-attempt"))
        body = {
          id: "old-attempt",
          item_type: "question",
          item_id: "old-question",
          status: "done",
          engine: "mock",
          duration_s: 5,
          overall: 80,
          item_text: "An older exchanged question",
          transcript: "I like reading.",
        }
      await route.fulfill({ json: body })
    })
    await page.goto("/t/GENERAL/s/student")
    await expect(
      page.getByText("History round 30", { exact: false }),
    ).toBeVisible()
    await expect(
      page.getByText("History round 31", { exact: false }),
    ).toHaveCount(0)
    await page
      .getByRole("button", { name: "加载更早记录", exact: true })
      .click()
    await expect(
      page.getByText("History round 31", { exact: false }),
    ).toBeVisible()
    await expect(
      page.getByText("History round 1", { exact: false }).first(),
    ).toBeVisible()
    await expect(
      page.getByRole("button", { name: "加载更早记录", exact: true }),
    ).toHaveCount(0)
    expect(offsets).toEqual([0, 30])
    await page.getByRole("button", { name: "作答反馈 1", exact: true }).click()
    await expect(
      page.getByRole("dialog").getByText("An older exchanged question"),
    ).toBeVisible()
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1)
  })
}
