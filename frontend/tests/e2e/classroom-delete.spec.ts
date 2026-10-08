import { expect, test } from "@playwright/test"

for (const width of [390, 820, 1180]) {
  test(`confirm classroom history deletion and recover from scoring conflict at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.addInitScript(() => {
      localStorage.setItem("access_token", "test-token")
      localStorage.setItem("esa:role", "teacher")
    })
    let deleted = false
    let deleteCalls = 0
    await page.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url())
      let body: unknown = []
      if (url.pathname.endsWith("/users/me"))
        body = {
          id: "teacher",
          role: "teacher",
          is_active: true,
          is_superuser: true,
        }
      else if (url.pathname.endsWith("/classes"))
        body = deleted
          ? []
          : [
              {
                id: "classroom",
                name: "Redundant test class",
                code: "DELETE",
                is_active: false,
                class_size: 10,
              },
            ]
      else if (
        url.pathname.endsWith("/classes/DELETE") &&
        route.request().method() === "DELETE"
      ) {
        expect(url.searchParams.get("delete_history")).toBe("true")
        deleteCalls += 1
        if (deleteCalls === 1) {
          await route.fulfill({
            status: 409,
            json: { detail: "有正在评分中的作答，请稍后再删除" },
          })
          return
        }
        deleted = true
        body = { message: "课堂已删除" }
      }
      await route.fulfill({ json: body })
    })
    await page.goto("/classrooms")
    await page.getByText("学生管理 · 名单与账号", { exact: true }).click()
    await page.getByRole("button", { name: "删除课堂", exact: true }).click()
    const dialog = page.getByRole("dialog")
    await expect(dialog.getByText(/永久删除.*全部口语\/词汇作答/)).toBeVisible()
    await dialog.getByRole("button", { name: "删除课堂", exact: true }).click()
    await expect(
      page.getByText("有正在评分中的作答，请稍后再删除", { exact: true }),
    ).toBeVisible()
    await expect(dialog).toBeVisible()
    await expect(
      dialog.getByRole("button", { name: "删除课堂", exact: true }),
    ).toBeEnabled()
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1)
    await dialog.getByRole("button", { name: "删除课堂", exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(
      page.getByText("Redundant test class", { exact: true }),
    ).toHaveCount(0)
    expect(deleteCalls).toBe(2)
  })
}
