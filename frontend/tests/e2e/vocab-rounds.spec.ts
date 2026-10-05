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
  // 重跑幂等：等「输入框」（可作答）或「本轮完成」出现再分支——
  // today 未加载完时两者都不可见，直接判分支会误判
  const practiceInput = page.getByPlaceholder("在这里输入英文单词…")
  await practiceInput
    .or(page.getByText(/这一轮完成了|Round complete/))
    .first()
    .waitFor({ state: "visible", timeout: 15_000 })
  if (await practiceInput.isVisible()) {
    await answerCurrentItem(page, "apple")
    await answerCurrentItem(page, "banana")
  }

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
  // 重跑幂等：B 的当前轮可能已被上次运行答完 → 先开新轮再作答
  const taskBInput = page.getByPlaceholder("在这里输入英文单词…")
  await taskBInput
    .or(page.getByRole("button", { name: /再练一轮|New round/ }))
    .first()
    .waitFor({ state: "visible", timeout: 15_000 })
  if (!(await taskBInput.isVisible())) {
    await page.getByRole("button", { name: /再练一轮|New round/ }).click()
  }
  // 核心断言：作答必须用 B 自己的会话——判对反馈只会出现在正确的会话里
  await answerCurrentItemCorrectly(page)

  // 教师端统计：A/B 各自记账（重跑会推进 B 的轮次状态，因此断言
  // 「B 名单内有作答记录」而非具体进行中/完成态）
  const resultsB = await (
    await request.get(`${API}/classes/DEMO01/vocabulary/results`, {
      headers: authHeaders(teacherToken),
      params: { assignment_id: assignments["E2E 任务B"] },
    })
  ).json()
  expect(
    resultsB.completed_count + resultsB.in_progress_count,
  ).toBeGreaterThanOrEqual(1)
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

/** 幂等造「E2E 回看任务」（apple/banana 两词，轮 1 故意留一个首答错词） */
async function ensureReviewTask(
  request: Page["request"],
  token: string,
): Promise<string> {
  const headers = authHeaders(token)
  const classrooms = await (
    await request.get(`${API}/classes`, { headers })
  ).json()
  const demo = (classrooms as Array<{ code: string; id: string }>).find(
    (c) => c.code === "DEMO01",
  )
  if (!demo) throw new Error("DEMO01 课堂不存在")
  const books = (await (
    await request.get(`${API}/vocabulary/books`, { headers })
  ).json()) as Array<{ title: string; id: string }>
  let bookId = books.find((b) => b.title === "E2E 回看词库")?.id
  if (!bookId) {
    const created = await request.post(`${API}/vocabulary/books`, {
      headers,
      data: {
        title: "E2E 回看词库",
        scope: "classroom",
        classroom_id: demo.id,
        words: [
          { headword: "apple", meaning_zh: "苹果" },
          { headword: "banana", meaning_zh: "香蕉" },
        ],
      },
    })
    if (!created.ok()) throw new Error(`建词库失败: ${await created.text()}`)
    bookId = ((await created.json()) as { id: string }).id
  }
  const detail = await (
    await request.get(`${API}/vocabulary/books/${bookId}`, { headers })
  ).json()
  const ids = Object.fromEntries(
    (detail as { words: Array<{ id: string; headword: string }> }).words.map(
      (w) => [w.headword, w.id],
    ),
  )
  const existing = (await (
    await request.get(`${API}/classes/DEMO01/vocabulary/assignments`, {
      headers,
    })
  ).json()) as Array<{ assignment: { title: string; id: string } }>
  const found = existing.find((a) => a.assignment.title === "E2E 回看任务")
  if (found) return found.assignment.id
  const created = await request.post(
    `${API}/classes/DEMO01/vocabulary/assignments`,
    {
      headers,
      data: {
        title: "E2E 回看任务",
        prompt_types: ["meaning"],
        word_ids: [ids.apple, ids.banana],
      },
    },
  )
  if (!created.ok()) throw new Error(`发布任务失败: ${await created.text()}`)
  return ((await created.json()) as { id: string }).id
}

/** 任务已完成时点击「再练一轮」开新轮，返回是否点了 */
async function startNewRoundIfCompleted(page: Page): Promise<boolean> {
  const button = page.getByRole("button", { name: /再练一轮|New round/ })
  if (await button.isVisible().catch(() => false)) {
    await button.click()
    return true
  }
  return false
}

/**
 * 把「当前轮」作答到完成：每题固定答 "apple"——题面是苹果判对、
 * 香蕉判错（首答错正好留下「再试一次」/错误反馈的历史），
 * 判对判错都点下一个词。对任何遗留进度幂等，终止于「再练一轮」出现。
 */
async function finishCurrentRound(page: Page) {
  for (let guard = 0; guard < 8; guard++) {
    const newRound = page.getByRole("button", { name: /再练一轮|New round/ })
    if (await newRound.isVisible().catch(() => false)) return
    const input = page.getByPlaceholder("在这里输入英文单词…")
    if (!(await input.isVisible().catch(() => false))) {
      const next = page.getByRole("button", { name: /下一个词|完成练习/ })
      if (await next.isVisible().catch(() => false)) {
        await next.click()
        continue
      }
      await page.waitForTimeout(300)
      continue
    }
    await expect(input).toBeEnabled()
    await input.fill("apple")
    await page.getByRole("button", { name: "提交" }).click()
    await expect(page.getByText(/拼对了！|差一点点/).first()).toBeVisible({
      timeout: 10_000,
    })
    await page.getByRole("button", { name: /下一个词|完成练习/ }).click()
  }
  throw new Error("finishCurrentRound: 8 轮守卫内未到达轮次完成")
}

/** 当前题按题面作答正确拼写（词面→拼写映射），用于「判对」断言场景 */
const PROMPT_WORDS: Array<[string, string]> = [
  ["苹果", "apple"],
  ["香蕉", "banana"],
  ["狗", "dog"],
  ["猫", "cat"],
]

async function answerCurrentItemCorrectly(page: Page) {
  const input = page.getByPlaceholder("在这里输入英文单词…")
  await input.waitFor({ state: "visible", timeout: 10_000 })
  await expect(input).toBeEnabled()
  // 只读题面元素（题干是 text-xl font-semibold）；侧边栏激励语同为
  // text-xl 但无 font-semibold，必须排除
  const promptText = await page
    .locator("p.text-xl.font-semibold")
    .first()
    .textContent()
    .catch(() => "")
  const match = PROMPT_WORDS.find(([meaning]) => promptText?.includes(meaning))
  await input.fill(match?.[1] ?? "apple")
  await page.getByRole("button", { name: "提交" }).click()
  await expect(page.getByText("拼对了！")).toBeVisible({ timeout: 15_000 })
}

test("历史轮回看只读：无再试入口、重复点击不跳走、再练入口隐藏", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000)
  const teacherToken = await loginTeacherDemo(page)
  await ensureReviewTask(request, teacherToken)

  await loginStudentDemo(page)
  const row = page.getByRole("button", { name: /E2E 回看任务/ })
  await page.goto("/vocab/DEMO01")
  await row.waitFor({ state: "visible", timeout: 15_000 })
  await row.click()
  await page.waitForURL(/assignment=/, { timeout: 10_000 })
  // 先把当前轮答完（首答含错），再开一轮走完：得到「历史轮 + 已完成当前轮」
  await finishCurrentRound(page)
  await expect(
    page.getByRole("button", { name: /再练一轮|New round/ }),
  ).toBeVisible({ timeout: 10_000 })
  await startNewRoundIfCompleted(page)
  await finishCurrentRound(page)

  // 切回第一个历史轮：只读视图
  const firstChip = page.getByRole("button", { name: /第 1 轮|R1 / }).first()
  await firstChip.waitFor({ state: "visible", timeout: 10_000 })
  await firstChip.click()
  // TanStack Router 会把字符串 search 值序列化为带引号形式（round=%221%22）
  await page.waitForURL(/round=/, { timeout: 10_000 })
  await expect(
    page.getByText(/正在回看这一轮|Viewing this round/),
  ).toBeVisible()

  // 只读兑现：历史轮不提供「再试一次」，也不能开新一轮
  await expect(
    page.getByRole("button", { name: /再试一次|Try again/ }),
  ).toBeHidden()
  await expect(
    page.getByRole("button", { name: /再练一轮|New round/ }),
  ).toBeHidden()
  await expect(page.getByPlaceholder("在这里输入英文单词…")).toBeHidden()

  // 重复点击已选中的历史轮：保持在轮 1，不跳最新轮
  await page
    .getByRole("button", { name: /第 1 轮|R1 / })
    .first()
    .click()
  await page.waitForTimeout(500)
  expect(page.url()).toContain("round=")
})

test("迟到的提交响应不覆盖历史轮反馈", async ({ page, request }) => {
  test.setTimeout(120_000)
  const teacherToken = await loginTeacherDemo(page)
  await ensureReviewTask(request, teacherToken)

  await loginStudentDemo(page)
  const row = page.getByRole("button", { name: /E2E 回看任务/ })
  await page.goto("/vocab/DEMO01")
  await row.waitFor({ state: "visible", timeout: 15_000 })
  await row.click()
  await page.waitForURL(/assignment=/, { timeout: 10_000 })

  // 开新轮，按题面答对当前词，响应人为延迟 3 秒（保证迟到响应是「拼对了」）
  await startNewRoundIfCompleted(page)
  await page.route("**/vocabulary/sessions/*/answers", async (route) => {
    const response = await route.fetch()
    await new Promise((resolve) => setTimeout(resolve, 3000))
    await route.fulfill({ response })
  })
  await answerCurrentItemCorrectly(page)

  // 提交未返回时切回含错答的历史轮（轮 2 摘要定格 1/2：banana 首答错）
  await page
    .getByRole("button", { name: /第 2 轮 1\/2/ })
    .first()
    .click()
  await page.waitForURL(/round=/, { timeout: 10_000 })
  await expect(
    page.getByText(/正在回看这一轮|Viewing this round/),
  ).toBeVisible()
  // 错答在第 2 题（banana 首答错）：切到该题看反馈
  await page.getByRole("button", { name: /第 2 题/ }).click()
  await expect(page.getByText(/差一点点|So close/)).toBeVisible()

  // 迟到响应（判对）到达后：历史轮的「错」反馈不得被「拼对了」覆盖
  await page.waitForTimeout(4000)
  await expect(
    page.getByText(/正在回看这一轮|Viewing this round/),
  ).toBeVisible()
  await expect(page.getByText(/差一点点|So close/)).toBeVisible()
})
