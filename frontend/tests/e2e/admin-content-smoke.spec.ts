import { expect, type Page, test } from "@playwright/test"

/**
 * 管理端内容页冒烟（依赖本地演示超管登录）。此前 admin 域只有篇目页与
 * 用户分页有覆盖；这里补「单元管理」与「句型库」两页的最基础回归：
 * 页面能开、标题与核心新区块在渲染。不点任何写操作。
 */

async function loginAdminDemo(page: Page) {
  await page.goto("/login")
  await page.getByText("本地演示体验", { exact: false }).click()
  await page.getByRole("button", { name: "教师演示" }).click()
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 15_000,
  })
}

test("管理端单元管理页渲染", async ({ page }) => {
  await loginAdminDemo(page)
  await page.goto("/admin/units")
  await expect(
    page.getByRole("heading", { name: /单元管理|Unit Management/ }),
  ).toBeVisible()
  // 新建表单入口在（是否展开不影响断言，能开即可）
  await expect(
    page.getByRole("button", { name: /新建单元|New Unit/ }).first(),
  ).toBeVisible()
})

test("管理端句型库页渲染", async ({ page }) => {
  await loginAdminDemo(page)
  await page.goto("/admin/sentenceframes")
  await expect(
    page.getByRole("heading", { name: /句型库|Sentence Frames/ }),
  ).toBeVisible()
})
