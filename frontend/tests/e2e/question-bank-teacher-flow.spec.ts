import { expect, type Page, test } from "@playwright/test"

/**
 * 普通教师全流程（非超管账号）：导入 → 查看本批 → 带入组卷（预选）→ 发布。
 *
 * 种子阶段用演示管理员建「教师角色账号 + 课堂」；界面操作全部以该教师
 * 账号登录完成——验证权限口径与自助闭环（不依赖管理员代操作）。
 */

const TEACHER_EMAIL = "e2e-teacher-flow@example.com"
const TEACHER_PASSWORD = "e2e-teacher-pass-123"

async function seedTeacherAndClassroom(page: Page): Promise<string> {
  const demo = await page.request.post("/api/v1/login/demo")
  expect(demo.ok()).toBeTruthy()
  const adminToken = ((await demo.json()) as { access_token: string })
    .access_token
  const auth = { Authorization: `Bearer ${adminToken}` }

  // 建普通教师（角色 teacher，非超管）；已存在则复用
  await page.request.post("/api/v1/users/", {
    headers: auth,
    data: {
      email: TEACHER_EMAIL,
      password: TEACHER_PASSWORD,
      role: "teacher",
    },
  })
  // 教师自建课堂（教师权限内）
  const teacherLogin = await page.request.post("/api/v1/login/access-token", {
    form: { username: TEACHER_EMAIL, password: TEACHER_PASSWORD },
  })
  expect(teacherLogin.ok()).toBeTruthy()
  const teacherToken = ((await teacherLogin.json()) as { access_token: string })
    .access_token
  const classroom = await page.request.post("/api/v1/classes", {
    headers: { Authorization: `Bearer ${teacherToken}` },
    data: { class_size: 10 },
  })
  expect(classroom.ok()).toBeTruthy()
  const code = ((await classroom.json()) as { code: string }).code

  // 同主题放一道「旧题」：验证带入组卷只出新批题目、不混入旧题
  const oldSeed =
    `\ufeff题型,标题,单元,主题,难度,内容,中文提示,挂靠篇目,秒数,可听次数,考试题型,考试级别,话题卡要点,准备秒数,音频链接,状态\n` +
    `情景问答,,,e2e-old-topic,,OLD question that must stay out,,,20,,,,,,,,,\n`
  const seedResp = await page.request.post(
    "/api/v1/admin/question-bank/import-confirm",
    {
      headers: { Authorization: `Bearer ${teacherToken}` },
      multipart: {
        file: {
          name: "old.csv",
          mimeType: "text/csv",
          buffer: Buffer.from(oldSeed, "utf-8"),
        },
        include_lines: "",
      },
    },
  )
  expect(seedResp.ok()).toBeTruthy()
  return code
}

async function loginTeacher(page: Page) {
  await page.goto("/login")
  await page
    .getByLabel(/邮箱|Email/)
    .first()
    .fill(TEACHER_EMAIL)
  await page
    .getByLabel(/密码|Password/)
    .first()
    .fill(TEACHER_PASSWORD)
  await page.getByRole("button", { name: /登录|Sign in/ }).click()
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 15_000,
  })
}

test("普通教师：导入 → 查看本批 → 带入组卷 → 发布", async ({ page }) => {
  test.setTimeout(120_000)
  const code = await seedTeacherAndClassroom(page)
  const marker = `flow-${Date.now()}`
  await loginTeacher(page)

  // 暖缓存路径（评审 P2）：先访问课堂把组卷题库查询缓存住（不含新题），
  // 之后再导入并返回——预选必须等刷新后的数据，而不是消费旧缓存丢新题
  await page.goto(`/t/${code}`)
  await expect(page.getByRole("button", { name: /预览练习/ })).toBeVisible({
    timeout: 20_000,
  })

  // ── 导入：/create 批量导入弹窗全链路 ──
  await page.goto("/create")
  await page.getByRole("button", { name: /^批量导入$/ }).click()
  const dialog = page.getByRole("dialog")
  const fileInput = dialog.locator('input[type="file"]')
  const csv = Buffer.from(
    `\ufeff题型,标题,单元,主题,难度,内容,中文提示,挂靠篇目,秒数,可听次数,考试题型,考试级别,话题卡要点,准备秒数,音频链接,状态\n` +
      `情景问答,,,e2e-old-topic,,${marker} Which place do you like best?,,,20,,,,,,,,,\n`,
    "utf-8",
  )
  await fileInput.setInputFiles({
    name: "teacher-flow.csv",
    mimeType: "text/csv",
    buffer: csv,
  })
  await dialog.getByRole("button", { name: /^预览$/ }).click()
  await expect(dialog.getByText(/将导入 1/)).toBeVisible()
  await dialog.getByRole("button", { name: /确认导入/ }).click()
  await expect(dialog.getByText(/新建 1/)).toBeVisible()

  // ── 查看本批：只含本批新建题目 ──
  await dialog.getByRole("button", { name: /查看本批题目（1）/ }).click()
  await expect(
    dialog.getByText(new RegExp(`${marker} Which place`)),
  ).toBeVisible()

  // ── 带入组卷：无课堂上下文 → 跳课堂列表，进入教师自己的课堂 ──
  await dialog.getByRole("button", { name: /带入组卷/ }).click()
  await page.waitForURL((url) => url.pathname === "/classrooms", {
    timeout: 15_000,
  })
  // 落到课堂列表（老师自选课堂）；课堂卡可见后进入自己刚建的课堂。
  // 预选经 sessionStorage 跨页面导航保留。
  await expect(page.getByText(new RegExp(code))).toBeVisible({
    timeout: 15_000,
  })
  await page.goto(`/t/${code}`)

  // 组卷页：预选生效（问答主题被带入且勾选），预览发布入口可见
  const composer = page.getByRole("main")
  await expect(composer.getByText(/e2e-old-topic/).first()).toBeVisible({
    timeout: 15_000,
  })
  await expect(composer.getByRole("button", { name: /预览练习/ })).toBeEnabled()

  // ── 发布（老师检查后自行确认；不自动发布）──
  await composer.getByRole("button", { name: /预览练习/ }).click()
  const previewDialog = page.getByRole("dialog")
  await expect(previewDialog.getByText(marker)).toBeVisible()
  // 题目级白名单：同主题旧题不得混入本批题单
  await expect(
    previewDialog.getByText("OLD question that must stay out"),
  ).toHaveCount(0)
  await previewDialog.getByRole("button", { name: /确认发布到课堂/ }).click()
  await expect(page.getByText(/本次课堂练习已发布/)).toBeVisible({
    timeout: 15_000,
  })
})
