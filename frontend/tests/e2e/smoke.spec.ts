import { expect, test } from "@playwright/test"

/**
 * 主干道冒烟（依赖 local 环境的演示登录入口）：
 * 登录页渲染 → 角色入口切换 → 教师演示登录 → 课堂面板 → 题目库三题型。
 * 抓的是「页面能开、核心交互能点、关键区块在渲染」这类基础回归。
 */

test("登录页渲染与学生/教师入口切换", async ({ page }) => {
  await page.goto("/login")
  await expect(
    page.getByRole("heading", { name: "欢迎来到 Charcoal" }),
  ).toBeVisible()
  // 默认教师 Tab：邮箱输入
  await expect(page.getByPlaceholder("请输入你的邮箱")).toBeVisible()
  // 切到学生 Tab：学号输入出现
  await page.getByRole("tab", { name: "学生登录" }).click()
  await expect(page.getByPlaceholder("请输入你的学号")).toBeVisible()
})

test("教师演示登录进入教学工作台与题目库三题型", async ({ page }) => {
  await page.goto("/login")
  await page.getByText("本地演示体验", { exact: false }).click()
  await page.getByRole("button", { name: "教师演示" }).click()
  // loginDemo 成功后离开登录页进入教学工作台（落点随本地数据而定）
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 15_000,
  })
  await expect(page.getByRole("link", { name: "我的课堂" })).toBeVisible()

  // 题目库：三种题型卡
  await page.getByRole("link", { name: "题目库" }).click()
  await expect(
    page.getByRole("heading", { name: "题目库", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText("文章朗读", { exact: false }).first(),
  ).toBeVisible()
  await expect(
    page.getByText("听句复述", { exact: false }).first(),
  ).toBeVisible()
  await expect(
    page.getByText("情景问答", { exact: false }).first(),
  ).toBeVisible()
})
