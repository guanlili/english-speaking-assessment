import { expect, type Page, test } from "@playwright/test"

/**
 * 词汇多任务/多轮浏览器回归（评审 P1/P2 对应）：
 * 1. 跨任务错投：完成 A 后刷新仍固定 A；进入 B 作答必须走 B 的会话
 *    （错投时 dog 会被 A 的题判错，反馈不会出现「拼对了」）。
 * 2. 教师词汇页在真实任务数据 + 英文界面 + 三档宽度下无横向溢出
 *    （期数选择器 option 文案很长，是 390px 溢出的源头）。
 *
 * 数据用后端 API 直接造（demo 教师登录后的 token 调管理接口），
 * 标题固定并按同名去重，保证重跑幂等、不往演示库堆重复任务。
 */

const API = "/api/v1"

/** 教师演示登录并返回 API token（供 page.request 造数据） */
async function loginTeacherDemo(page: Page): Promise<string> {
  await page.goto("/login")
  await page.getByText("本地演示体验", { exact: false }).click()
  await page.getByRole("button", { name: "教师演示" }).click()
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 15_000,
  })
  const token = await page.evaluate(() => localStorage.getItem("access_token"))
  if (!token) throw new Error("教师演示登录未拿到 token")
  return token
}

async function tryStudentPassword(
  page: Page,
  password: string,
): Promise<boolean> {
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

async function loginStudentDemo(page: Page) {
  // 教师造数据后同一页面已带登录态：清掉本地凭据再走学生登录
  await page.goto("/login")
  await page.evaluate(() => localStorage.clear())
  await page.goto("/login")
  await page.getByRole("tab", { name: "学生登录" }).click()
  await page.getByPlaceholder("请输入你的学号").fill("student")
  const signedIn =
    (await tryStudentPassword(page, "demo1234")) ||
    (await tryStudentPassword(page, "brs123456"))
  if (!signedIn) {
    throw new Error("学生演示登录失败：demo1234 与 brs123456 均未通过")
  }
  await page.goto("/j/DEMO01")
  const hasIdentity = () =>
    page.waitForFunction(
      () => localStorage.getItem("esa:student:DEMO01") !== null,
      undefined,
      { timeout: 8_000, polling: 250 },
    )
  if (
    !(await hasIdentity().then(
      () => true,
      () => false,
    ))
  ) {
    const joinButton = page.getByRole("button", { name: /进入课堂|Join class/ })
    await joinButton.waitFor({ state: "visible", timeout: 10_000 })
    await joinButton.click()
    await hasIdentity()
  }
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` }
}

/** 幂等造两个任务（各 2 词），返回任务标题 → id 映射 */
async function ensureTwoAssignments(
  request: Page["request"],
  token: string,
): Promise<Record<string, string>> {
  const headers = authHeaders(token)
  const classrooms = await (
    await request.get(`${API}/classes`, { headers })
  ).json()
  const demo = (classrooms as Array<{ code: string; id: string }>).find(
    (c) => c.code === "DEMO01",
  )
  if (!demo) throw new Error("DEMO01 课堂不存在")

  const books = await (
    await request.get(`${API}/vocabulary/books`, { headers })
  ).json()
  const booksList = books as Array<{ title: string; id: string }>
  let bookId = booksList.find((b) => b.title === "E2E 多任务词库")?.id
  if (!bookId) {
    const created = await request.post(`${API}/vocabulary/books`, {
      headers,
      data: {
        title: "E2E 多任务词库",
        scope: "classroom",
        classroom_id: demo.id,
        words: [
          { headword: "apple", meaning_zh: "苹果" },
          { headword: "banana", meaning_zh: "香蕉" },
          { headword: "dog", meaning_zh: "狗" },
          { headword: "cat", meaning_zh: "猫" },
        ],
      },
    })
    if (!created.ok()) throw new Error(`建词库失败: ${await created.text()}`)
    bookId = ((await created.json()) as { id: string }).id
  }
  const detail = await (
    await request.get(`${API}/vocabulary/books/${bookId}`, { headers })
  ).json()
  const words = (detail as { words: Array<{ id: string; headword: string }> })
    .words
  const ids = Object.fromEntries(words.map((w) => [w.headword, w.id]))

  const plan = [
    { title: "E2E 任务A", heads: ["apple", "banana"] },
    { title: "E2E 任务B", heads: ["dog", "cat"] },
  ]
  const existing = (await (
    await request.get(`${API}/classes/DEMO01/vocabulary/assignments`, {
      headers,
    })
  )
    // 教师列表行结构是 {assignment: {...}, ...}，标题嵌套在 assignment 里
    .json()) as Array<{ assignment: { title: string; id: string } }>
  const result: Record<string, string> = {}
  for (const spec of plan) {
    const found = existing.find((a) => a.assignment.title === spec.title)
    if (found) {
      result[spec.title] = found.assignment.id
      continue
    }
    const created = await request.post(
      `${API}/classes/DEMO01/vocabulary/assignments`,
      {
        headers,
        data: {
          title: spec.title,
          prompt_types: ["meaning"],
          word_ids: spec.heads.map((head) => ids[head]),
        },
      },
    )
    if (!created.ok()) throw new Error(`发布任务失败: ${await created.text()}`)
    result[spec.title] = ((await created.json()) as { id: string }).id
  }
  return result
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
}

async function answerCurrentItem(page: Page, word: string) {
  const input = page.getByPlaceholder("在这里输入英文单词…")
  await input.waitFor({ state: "visible", timeout: 10_000 })
  // 输入框禁用（readOnly/会话未就绪）时直接失败，暴露竞态
  await expect(input).toBeEnabled()
  await input.fill(word)
  await page.getByRole("button", { name: "提交" }).click()
  // 判对反馈只有用了当前任务的会话才会出现（错投到别的任务会判错）
  await expect(page.getByText("拼对了！")).toBeVisible({ timeout: 10_000 })
  await page.getByRole("button", { name: /下一个词|完成练习/ }).click()
}

test("多任务练习：完成 A 后刷新仍固定 A，进入 B 作答不串任务", async ({
  page,
  request,
}) => {
  test.setTimeout(90_000)
  const teacherToken = await loginTeacherDemo(page)
  const assignments = await ensureTwoAssignments(request, teacherToken)

  await loginStudentDemo(page)
  await page.goto("/vocab/DEMO01")
  const rowA = page.getByRole("button", { name: /E2E 任务A/ })
  const rowB = page.getByRole("button", { name: /E2E 任务B/ })
  await rowA.waitFor({ state: "visible", timeout: 15_000 })
  await expect(rowB).toBeVisible()

  // 进入任务 A：URL 固定任务 ID（P1 修复：进入练习即固定，不再随聚焦漂移）
  await rowA.click()
  await page.waitForURL(/assignment=/, { timeout: 10_000 })
  expect(page.url()).toContain(`assignment=${assignments["E2E 任务A"]}`)
  await answerCurrentItem(page, "apple")
  await answerCurrentItem(page, "banana")

  // 完成后刷新：仍固定在任务 A，题面不切换到任务 B（修复前这里会漂移）
  await page.reload()
  await page.waitForURL(/assignment=/, { timeout: 10_000 })
  expect(page.url()).toContain(`assignment=${assignments["E2E 任务A"]}`)
  await expect(page.getByText("苹果").first()).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText("狗").first()).toBeHidden()

  // 回首页进入任务 B：作答 dog 必须判对（错投 A 会话会把 dog 判错）
  await page
    .getByRole("link", { name: /返回词汇学习|Back to Vocabulary/ })
    .click()
  await rowB.click()
  await page.waitForURL(/assignment=/, { timeout: 10_000 })
  expect(page.url()).toContain(`assignment=${assignments["E2E 任务B"]}`)
  await answerCurrentItem(page, "dog")

  // 教师端统计：A 完成不受 B 影响，B 记录进 B 自己的会话
  const results = await (
    await request.get(`${API}/classes/DEMO01/vocabulary/results`, {
      headers: authHeaders(teacherToken),
      params: { assignment_id: assignments["E2E 任务B"] },
    })
  ).json()
  expect(results.in_progress_count).toBeGreaterThanOrEqual(1)
  const done = await (
    await request.get(`${API}/classes/DEMO01/vocabulary/results`, {
      headers: authHeaders(teacherToken),
      params: { assignment_id: assignments["E2E 任务A"] },
    })
  ).json()
  expect(done.completed_count).toBeGreaterThanOrEqual(1)
})

test("教师词汇页真实任务在英文界面三档宽度无横向溢出", async ({
  page,
  request,
}) => {
  test.setTimeout(90_000)
  const teacherToken = await loginTeacherDemo(page)
  await ensureTwoAssignments(request, teacherToken)

  await page.goto("/t/DEMO01/vocab")
  // 有真实任务：当前任务概览 + 任务列表 + 期数选择器都在渲染
  await expect(page.getByText(/E2E 任务A/).first()).toBeVisible({
    timeout: 15_000,
  })
  await page.getByRole("button", { name: /完成情况|Results/ }).click()
  await expect(page.getByText(/查看期数|Round:/).first()).toBeVisible()

  // 切英文界面（溢出复现条件：英文 option 文案更长）
  await page
    .getByRole("banner")
    .getByRole("button", { name: "EN", exact: true })
    .first()
    .click()
  await expect(page.getByText(/Round:/).first()).toBeVisible()

  for (const vp of [
    { name: "390", width: 390, height: 844 },
    { name: "820", width: 820, height: 1180 },
    { name: "1180", width: 1180, height: 820 },
  ]) {
    await page.setViewportSize({ width: vp.width, height: vp.height })
    await expect(page.getByText(/Round:/).first()).toBeVisible()
    await expectNoHorizontalOverflow(page)
  }
})
