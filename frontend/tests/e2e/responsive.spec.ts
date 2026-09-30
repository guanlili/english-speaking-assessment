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
