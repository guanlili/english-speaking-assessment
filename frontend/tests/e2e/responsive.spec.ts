import { expect, test } from "@playwright/test"

/**
 * 三端自适应冒烟：手机（390）/ iPad 竖屏（820）/ 桌面与 iPad 横屏（1180）。
 * 平台要求电脑/手机/平板都可用，iPad 是学生上课主力（CLAUDE.md「三端自适应准则」）。
 * 断言核心：无横向溢出（scrollWidth 不超过视宽）+ 关键交互元素可见。
 */

const VIEWPORTS = [
  { name: "手机 390", width: 390, height: 844 },
  { name: "iPad 竖屏 820", width: 820, height: 1180 },
  { name: "桌面/iPad 横屏 1180", width: 1180, height: 820 },
]

for (const vp of VIEWPORTS) {
  test(`登录页在${vp.name}无横向溢出且语言切换可见`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height })
    await page.goto("/login")

    // 无横向溢出（1px 容差）
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(1)

    // 双语切换入口在任何尺寸都可见可点
    await expect(
      page.getByRole("group", { name: "语言 / Language" }),
    ).toBeVisible()

    // 底部导航在小屏可用：iPad/手机上学生走底部 tab（登录页至少不应被裁切）
    const bodyWidth = await page.evaluate(
      () => document.body.getBoundingClientRect().width,
    )
    expect(bodyWidth).toBeLessThanOrEqual(vp.width)
  })
}

test("iPad 竖屏下进入课堂页布局正常", async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 1180 })
  await page.goto("/join")
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
})

/** 教师演示登录（本地超管 token），供词汇任务页复用 */
async function loginTeacherDemo(page: import("@playwright/test").Page) {
  await page.goto("/login")
  await page.getByText("本地演示体验", { exact: false }).click()
  await page.getByRole("button", { name: "教师演示" }).click()
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 15_000,
  })
}

/** 学生学号登录（本地演示学生 student）并完成一次幂等入班，
 * 让浏览器建立本课堂的学生身份（词汇页守卫依赖本地身份）。
 * 密码：CI 种子是 demo1234；本地开发库可能被批量重置为 brs123456，依次尝试。 */
async function tryStudentPassword(
  page: import("@playwright/test").Page,
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

async function loginStudentDemo(page: import("@playwright/test").Page) {
  await page.goto("/login")
  await page.getByRole("tab", { name: "学生登录" }).click()
  await page.getByPlaceholder("请输入你的学号").fill("student")
  const signedIn =
    (await tryStudentPassword(page, "demo1234")) ||
    (await tryStudentPassword(page, "brs123456"))
  if (!signedIn) {
    throw new Error("学生演示登录失败：demo1234 与 brs123456 均未通过")
  }
  // 登录后先到入班页完成一次幂等入班（已入班会自动建立本地身份），
  // 等到 esa:student:DEMO01 落盘再离开；需要手动点按钮时点它
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

async function expectNoHorizontalOverflow(
  page: import("@playwright/test").Page,
) {
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
}

for (const vp of VIEWPORTS) {
  test(`教师词汇任务页在${vp.name}无横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height })
    await loginTeacherDemo(page)
    await page.goto("/t/DEMO01/vocab")
    // 「发布任务 / 完成情况」切换恒在（有没有进行中任务都能断言页面就绪）
    await expect(
      page.getByRole("button", { name: /发布任务|Assign/ }),
    ).toBeVisible()
    await expect(
      page.getByRole("button", { name: /完成情况|Results/ }),
    ).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })

  test(`学生词汇学习页在${vp.name}无横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height })
    await loginStudentDemo(page)
    await page.goto("/vocab/DEMO01")
    await expect(
      page.getByRole("heading", { name: /词汇学习|Vocabulary/ }),
    ).toBeVisible()
    await expect(page.getByText(/错词本|Wrong Words/).first()).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })

  test(`学生词库浏览页在${vp.name}无横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height })
    await loginStudentDemo(page)
    await page.goto("/vocab/DEMO01/books")
    await expect(
      page.getByRole("heading", { name: /词库浏览|Word Books/ }),
    ).toBeVisible()
    // 搜索框与词库列表（或空态）就绪；有演示词库时至少一本可见
    await expect(
      page.getByPlaceholder(/搜索词库名称|Search word books/),
    ).toBeVisible()
    await expectNoHorizontalOverflow(page)
    // 选中词库展开词条列表：长词/长释义不得撑破布局（评审 390px 溢出）
    const anyBook = page.locator("main ul button").first()
    if ((await anyBook.count()) > 0) {
      await anyBook.click()
      await expect(
        page.getByPlaceholder(/搜库内单词|Search words or meanings/),
      ).toBeVisible()
      await expectNoHorizontalOverflow(page)
    }
  })

  test(`学生练习记录页在${vp.name}无横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height })
    await loginStudentDemo(page)
    await page.goto("/vocab/DEMO01/records")
    await expect(
      page.getByRole("heading", { name: /练习记录|Practice Records/ }),
    ).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })
}

test("学生自主练习页（无 session 参数）在手机宽度显示空态引导", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await loginStudentDemo(page)
  await page.goto("/vocab/DEMO01/self")
  await expect(
    page.getByRole("heading", { name: /还没有选择练习|No practice selected/ }),
  ).toBeVisible()
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
})
