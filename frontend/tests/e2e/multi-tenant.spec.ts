import { expect, test } from "@playwright/test"

/**
 * 多租户 AC-11：双租户端到端场景（integration 套件，真实后端，local 环境）。
 *
 * 链路：平台运营开校（/login/platform-demo 仅 local 开放）→ D1 给该校建号 →
 * B2 学校维度登录 → 断言：
 *  1. /s/{slug}/login 显示该校校名；未知 slug 显示中性错误（AC-03 不泄露）
 *  2. 乙校教师跨校读种子校（默认租户）课堂 → 403/404，列表不含其课堂码（AC-04/08）
 *  3. 已登录 UI「我的课堂」不出现种子校课堂码（AC-11 前端隔离）
 *
 * 数据自造自清（slug 带时间戳唯一），不依赖种子校账号。
 */

const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
const slug = `e2e-mt-${suffix}`.slice(0, 31)
const schoolName = "E2E双租户学校"
const teacherEmail = `mt-${slug}@example.com`
const teacherPassword = "E2ePassw0rd"

test("平台开校→建号→学校入口页与跨校隔离", async ({ page, request }) => {
  // 1) 平台运营登录开校
  const opResp = await request.post("/api/v1/login/platform-demo")
  expect(opResp.ok(), await opResp.text()).toBeTruthy()
  const opToken = (await opResp.json()).access_token as string

  const tenantResp = await request.post("/api/v1/admin/tenants", {
    headers: { Authorization: `Bearer ${opToken}` },
    data: { slug, name_zh: schoolName },
  })
  expect(tenantResp.ok(), await tenantResp.text()).toBeTruthy()
  expect((await tenantResp.json()).slug).toBe(slug)

  // 2) D1：给该校建教师账号（school 查询参数指定目标学校）
  const createResp = await request.post(`/api/v1/users/?school=${slug}`, {
    headers: { Authorization: `Bearer ${opToken}` },
    data: {
      email: teacherEmail,
      password: teacherPassword,
      role: "teacher",
      full_name: "E2E双租户教师",
    },
  })
  expect(createResp.ok(), await createResp.text()).toBeTruthy()

  // 3) B2：学校维度登录（同邮箱多校各自登录）
  const loginResp = await request.post(
    `/api/v1/login/access-token?school=${slug}`,
    { form: { username: teacherEmail, password: teacherPassword } },
  )
  expect(loginResp.ok(), await loginResp.text()).toBeTruthy()
  const token = (await loginResp.json()).access_token as string

  // 4) 学校入口页显示校名；未知 slug 显示中性错误（不泄露学校存在性）
  await page.goto(`/s/${slug}/login`)
  await expect(page.getByText(schoolName)).toBeVisible()

  await page.goto(`/s/no-such-school-${suffix}/login`)
  await expect(
    page.getByText("学校不存在或未开放，请检查链接是否正确"),
  ).toBeVisible()

  // 5) 跨校 API：乙校教师读种子校课堂 → 403/404；列表不含种子校课堂码
  const boardResp = await request.get("/api/v1/classes/DEMO01/board", {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect([403, 404]).toContain(boardResp.status())

  const listResp = await request.get("/api/v1/classes", {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(listResp.ok(), await listResp.text()).toBeTruthy()
  const rows = (await listResp.json()) as Array<{ code: string }>
  expect(rows.map((row) => row.code)).not.toContain("DEMO01")

  // 6) 已登录 UI：「我的课堂」不出现种子校课堂码
  await page.addInitScript(
    (t) => localStorage.setItem("access_token", t),
    token,
  )
  await page.goto("/classrooms")
  await expect(page.getByRole("heading", { name: "我的课堂" })).toBeVisible()
  await expect(page.getByText("DEMO01")).toHaveCount(0)
})
