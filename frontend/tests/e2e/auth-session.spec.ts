import { expect, test } from "@playwright/test"

// All requests are mocked; no backend or shared database state.
test("incorrect password keeps the form and error visible without reloading", async ({
  page,
}) => {
  let navigations = 0
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) navigations += 1
  })
  await page.route("**/api/v1/**", (route) => {
    if (route.request().url().includes("/login/access-token")) {
      return route.fulfill({
        status: 401,
        json: { detail: "账号或密码不正确" },
      })
    }
    return route.fulfill({
      json: { demo_enabled: false, registration_enabled: false },
    })
  })
  await page.goto("/login")
  await page.getByPlaceholder("请输入你的邮箱").fill("teacher@example.com")
  const password = page.locator('input[type="password"]')
  await password.fill("wrong-password")
  const before = navigations
  await page.getByRole("button", { name: "登录工作台", exact: true }).click()
  await expect(page.getByRole("alert").first()).toContainText(
    "账号或密码不正确",
  )
  await expect(password).toHaveValue("wrong-password")
  await expect(page.getByPlaceholder("请输入你的邮箱")).toHaveValue(
    "teacher@example.com",
  )
  expect(navigations).toBe(before)
})

test("sign out clears identity and imported batch before another teacher signs in", async ({
  page,
}) => {
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("initialized")) {
      sessionStorage.setItem("initialized", "1")
      localStorage.setItem("access_token", "teacher-a")
      localStorage.setItem("esa:role", "teacher")
      sessionStorage.setItem(
        "esa:qbank:composer-preset",
        '{"questions":["a-private-question"]}',
      )
    }
  })
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    const token = route.request().headers().authorization
    if (path.endsWith("/login/access-token"))
      return route.fulfill({
        json: { access_token: "teacher-b", token_type: "bearer" },
      })
    if (path.endsWith("/users/me"))
      return route.fulfill({
        json: {
          id: token === "Bearer teacher-a" ? "a" : "b",
          email:
            token === "Bearer teacher-a" ? "a@example.com" : "b@example.com",
          full_name:
            token === "Bearer teacher-a" ? "Teacher Alpha" : "Teacher Beta",
          role: "teacher",
          is_active: true,
          is_superuser: false,
          must_change_password: false,
        },
      })
    if (path.endsWith("/classes"))
      return route.fulfill({
        json: [
          {
            id: token === "Bearer teacher-a" ? "a-class" : "b-class",
            code: token === "Bearer teacher-a" ? "ALPHA1" : "BETA01",
            name:
              token === "Bearer teacher-a"
                ? "Alpha classroom"
                : "Beta classroom",
            is_active: true,
            class_size: 10,
          },
        ],
      })
    return route.fulfill({ json: [] })
  })
  await page.goto("/classrooms")
  await expect(page.getByText("Alpha classroom", { exact: true })).toBeVisible()
  await page.getByTestId("user-menu").click()
  await page.getByRole("menuitem", { name: "退出登录" }).click()
  await expect(page).toHaveURL(/\/login$/)
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem("esa:qbank:composer-preset"),
    ),
  ).toBeNull()
  expect(
    await page.evaluate(() => localStorage.getItem("access_token")),
  ).toBeNull()
  await page.getByPlaceholder("请输入你的邮箱").fill("b@example.com")
  await page.locator('input[type="password"]').fill("correct-password")
  await page.getByRole("button", { name: "登录工作台", exact: true }).click()
  await expect(page).not.toHaveURL(/\/login$/)
  await page.getByRole("link", { name: "我的课堂", exact: true }).click()
  await expect(page.getByText("Beta classroom", { exact: true })).toBeVisible()
  await expect(page.getByText("Alpha classroom", { exact: true })).toHaveCount(
    0,
  )
  await expect(page.getByTestId("user-menu")).toContainText("Teacher Beta")
})
