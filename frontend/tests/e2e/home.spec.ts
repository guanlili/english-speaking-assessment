import { expect, type Page, test } from "@playwright/test"

/**
 * 学生学习首页：hero 问候、今日计划摘要、连续打卡/XP、周目标环、
 * 开始练习入口跳转。全部 API 在网络层 mock，不依赖后端。
 */

const CODE = "HOME"

async function mockHome(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token")
    localStorage.setItem("esa:role", "student")
    localStorage.setItem(
      "esa:student:HOME",
      JSON.stringify({
        id: "student",
        display_name: "Student",
        suffix: null,
        user_id: "user",
      }),
    )
  })
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith("/users/me")) {
      body = {
        id: "user",
        role: "student",
        is_active: true,
        is_superuser: false,
      }
    } else if (path.endsWith("/today")) {
      body = {
        session_id: "home-session",
        classroom_code: CODE,
        band: "B1",
        items: [
          {
            type: "passage",
            id: "00000000-0000-4000-8000-000000000001",
            text: "A short passage for the home page.",
            suggested_seconds: 60,
          },
          {
            type: "question",
            id: "00000000-0000-4000-8000-000000000002",
            text: "What is your favorite season?",
            suggested_seconds: 60,
          },
        ],
        attempts: [],
        exam: null,
        gamification: { xp: 12, streak_days: 3 },
        assigned_unit_title: "Unit 1 Travel",
      }
    } else if (path.endsWith("/path")) {
      body = { classroom_code: CODE, unlock_all: false, units: [] }
    } else if (path.endsWith("/trail")) {
      body = {
        classroom_code: CODE,
        student_id: "student",
        display_name: "Student",
        suffix: null,
        sessions: [
          {
            date: new Date().toISOString(),
            attempt_count: 2,
            speaking_avg: 80,
          },
        ],
      }
    }
    await route.fulfill({ json: body })
  })
}

test("home hero, plan summary and gamification render", async ({ page }) => {
  await mockHome(page)
  await page.goto(`/home/${CODE}`)

  // hero：问候 + 今日单元 + CTA
  await expect(page.getByText("YOUR VOICE MATTERS")).toBeVisible()
  await expect(page.getByText("Hi，Student。")).toBeVisible()
  await expect(page.getByText("今日练习 · Unit 1 Travel")).toBeVisible()
  await expect(page.getByRole("button", { name: /开始今日练习/ })).toBeVisible()

  // 今日计划摘要与完成度
  await expect(page.getByText("1 篇朗读 + 1 道情景问答")).toBeVisible()
  await expect(page.getByText("0 / 2 已完成")).toBeVisible()

  // 周目标环：今天练过 1 天 / 默认目标 5 天
  await expect(page.getByText("本周开口目标")).toBeVisible()
  await expect(page.getByText("1", { exact: true })).toBeVisible()

  // CTA 跳转练习页
  await page.getByRole("button", { name: /开始今日练习/ }).click()
  await expect(page).toHaveURL(new RegExp(`/p/${CODE}`))
})

test("home week goal can be adjusted from the card", async ({ page }) => {
  await mockHome(page)
  await page.goto(`/home/${CODE}`)
  await expect(page.getByText("YOUR VOICE MATTERS")).toBeVisible()

  await page.getByRole("button", { name: "调整目标" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog).toBeVisible()
  await dialog.getByRole("button", { name: "3" }).click()
  await expect(page.getByText("每周目标已调整为 3 天")).toBeVisible()
})
