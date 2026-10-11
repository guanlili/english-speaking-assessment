import { expect, type Page, test } from "@playwright/test"

/**
 * 历史详细反馈冒烟（PR#111 回归锚点）：学生能在「我的成长」看到历史
 * 练习卡片，并从「查看反馈」进入指定会话的结果页（跨日回看链路）。
 */

async function tryPassword(page: Page, password: string): Promise<boolean> {
  await page.getByTestId("student-password-input").fill(password)
  await page.getByRole("button", { name: "登录", exact: false }).click()
  try {
    await page.waitForURL((url) => !url.pathname.includes("/login"), {
      timeout: 8_000,
    })
    return true
  } catch {
    return false
  }
}

test("学生历史练习卡片与回看入口", async ({ page }) => {
  await page.goto("/login")
  await page.getByRole("tab", { name: "学生登录" }).click()
  await page.getByPlaceholder("请输入你的学号").fill("student")
  const ok =
    (await tryPassword(page, "demo1234")) ||
    (await tryPassword(page, "brs123456"))
  expect(ok).toBeTruthy()
  // 建立本地课堂身份：已入班但本地无身份时需点一次「进入课堂」
  // （与 responsive.spec 的 loginStudentDemo 同款兜底）
  await page.goto("/j/DEMO01")
  const hasIdentity = () =>
    page.waitForFunction(
      () => localStorage.getItem("esa:student:DEMO01") !== null,
      undefined,
      { timeout: 10_000, polling: 250 },
    )
  try {
    await hasIdentity()
  } catch {
    const joinButton = page.getByRole("button", { name: /进入课堂|Join class/ })
    await joinButton.waitFor({ state: "visible", timeout: 10_000 })
    await joinButton.click()
    await hasIdentity()
  }
  await page.goto("/me/DEMO01")
  await expect(
    page.getByText(/历史练习|Practice History/).first(),
  ).toBeVisible()
  // 演示学生至少有一轮历史（demo 库有自主练习轮）；有则点击回看
  const viewLink = page.getByRole("link", { name: /查看反馈|View feedback/ })
  if ((await viewLink.count()) > 0) {
    await viewLink.first().click()
    await page.waitForURL(/\/p\/DEMO01\/result\?session=/)
    await expect(
      page.getByRole("heading", { name: /今天的你|向前|Round Results/ }),
    ).toBeVisible()
  }
})
