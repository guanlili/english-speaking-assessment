import { expect, type Page, test } from "@playwright/test"

/**
 * 管理员平台大盘冒烟（依赖本地演示运营登录——B3 起大盘归平台运营）：页面能开、速览卡/排行/
 * 资产区渲染。只读不写。教师 403 语义由后端测试覆盖。
 */

async function loginOperatorDemo(page: Page) {
  // B3 起平台大盘只认运营身份（演示一键运营会话）
  await page.goto("/login")
  await page.getByText("本地演示体验", { exact: false }).click()
  await page.getByRole("button", { name: "运营演示" }).click()
  await page.waitForURL((url) => url.pathname.includes("/admin"), {
    timeout: 15_000,
  })
}

test("管理端平台大盘渲染", async ({ page }) => {
  await loginOperatorDemo(page)
  await page.goto("/admin/dashboard")

  await expect(
    page.getByRole("heading", { name: /平台大盘|Platform Dashboard/ }),
  ).toBeVisible()

  // 速览卡：今日与区间两组各 6 张，取稳定文案断言
  await expect(page.getByText(/活跃学生|Active students/).first()).toBeVisible()
  await expect(page.getByText(/提交作答|Attempts/).first()).toBeVisible()

  // 时间范围档位可切换（切全部触发第二组请求）
  await page.getByRole("tab", { name: /全部|All/ }).click()
  await expect(page.getByText(/课堂使用排行|Classroom usage/)).toBeVisible()

  // 资产区标题在
  await expect(page.getByText(/资产与账号|Content & accounts/)).toBeVisible()

  // 性能与稳定区渲染（实时轮询区）
  await expect(page.getByText(/性能与稳定|Performance & health/)).toBeVisible()
  await expect(page.getByText("评分队列", { exact: true })).toBeVisible()
})
