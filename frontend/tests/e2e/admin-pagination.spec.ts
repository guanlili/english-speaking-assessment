import { expect, type Page, test } from "@playwright/test"

/**
 * 管理页服务端分页的破坏性操作安全（返修R01/R13回归）：
 * - R01：翻页数据到达后，同位置行换成另一个用户——旧页上打开的删除
 *   弹窗必须随稳定行 id 卸载，确认按钮绝不能对准新用户；
 *   页面抓取进行中行操作整体禁用（aria-busy + pointer-events-none）。
 * - R13：翻页失败显示错误卡与重试入口，不误报为空数据。
 * 全部 API 在网络层 mock，不依赖后端。
 */

interface MockUser {
  id: string
  email: string
  full_name: string | null
  is_active: boolean
  is_superuser: boolean
}

const PAGE_SIZE = 25

function pageUsers(page: number, prefix: string): MockUser[] {
  return Array.from({ length: PAGE_SIZE }, (_, i) => ({
    id: `user-${prefix}-${page}-${i}`,
    email: `u${page}-${i}@t.cn`,
    full_name: `${prefix}用户 ${page}-${String(i).padStart(2, "0")}`,
    is_active: true,
    is_superuser: false,
  }))
}

const firstPage = pageUsers(0, "甲")
const secondPage = pageUsers(1, "乙")

interface AdminMock {
  deleted: string[]
  setSlowNextPage: (ms: number) => void
  setSlowNextPageSize: (ms: number) => void
  failPageUntilAllowed: () => void
  allowPage: () => void
  /** 模拟远端变更：此后第一页返回乙页数据（不含任何甲行） */
  swapFirstPageToSecond: () => void
}

async function mockAdmin(page: Page): Promise<AdminMock> {
  const deleted: string[] = []
  const controls = {
    secondPageDelay: 0,
    pageSizeDelay: 0,
    failPage: false,
    firstPageSwapped: false,
  }
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token")
    localStorage.setItem("esa:role", "admin")
  })
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path.endsWith("/users/me")) {
      return route.fulfill({
        json: {
          id: "admin-me",
          role: "admin",
          is_active: true,
          is_superuser: true,
        },
      })
    }
    if (path.endsWith("/users/") && route.request().method() === "GET") {
      const skip = Number(url.searchParams.get("skip") ?? "0")
      const limit = Number(url.searchParams.get("limit") ?? "25")
      if (controls.failPage) {
        return route.fulfill({ status: 500, json: { detail: "boom" } })
      }
      if (limit !== PAGE_SIZE) {
        // 每页条数变更（另一查询键）：返回前 limit 条，构造「弹窗开着数据切换」
        if (controls.pageSizeDelay > 0) {
          await new Promise((resolve) =>
            setTimeout(resolve, controls.pageSizeDelay),
          )
        }
        return route.fulfill({
          json: { data: firstPage.slice(0, limit), count: PAGE_SIZE * 2 },
        })
      }
      if (skip === 0) {
        return route.fulfill({
          json: {
            data: controls.firstPageSwapped ? secondPage : firstPage,
            count: PAGE_SIZE * 2,
          },
        })
      }
      if (controls.secondPageDelay > 0) {
        await new Promise((resolve) =>
          setTimeout(resolve, controls.secondPageDelay),
        )
      }
      return route.fulfill({
        json: { data: secondPage, count: PAGE_SIZE * 2 },
      })
    }
    const deleteMatch = path.match(/\/users\/([^/]+)\/?$/)
    if (deleteMatch && route.request().method() === "DELETE") {
      deleted.push(deleteMatch[1])
      return route.fulfill({ json: { message: "ok" } })
    }
    return route.fulfill({ json: [] })
  })
  return {
    deleted,
    setSlowNextPage: (ms) => {
      controls.secondPageDelay = ms
    },
    setSlowNextPageSize: (ms) => {
      controls.pageSizeDelay = ms
    },
    failPageUntilAllowed: () => {
      controls.failPage = true
    },
    allowPage: () => {
      controls.failPage = false
    },
    swapFirstPageToSecond: () => {
      controls.firstPageSwapped = true
    },
  }
}

test("server-paginated admin list reaches page 2", async ({ page }) => {
  await mockAdmin(page)
  await page.goto("/admin")
  await expect(page.getByText("甲用户 0-00")).toBeVisible()
  await page.getByRole("button", { name: "下一页" }).click()
  await expect(page.getByText("乙用户 1-00")).toBeVisible()
})

test("R01: rows are inert while a page fetch is in flight (mouse + keyboard)", async ({
  page,
}) => {
  const mock = await mockAdmin(page)
  await page.goto("/admin")
  await expect(page.getByText("甲用户 0-00")).toBeVisible()

  mock.setSlowNextPage(1200)
  await page.getByRole("button", { name: "下一页" }).click()

  // 抓取进行中：表格区域 aria-busy + inert（鼠标与键盘都不可达）
  const busyTable = page.locator("div[aria-busy='true']")
  await expect(busyTable).toBeVisible()
  await expect(busyTable).toHaveAttribute("inert")
  // 键盘路径：聚焦旧行操作按钮后按 Enter，不得打开菜单
  const menuButton = page
    .locator("tr", { hasText: "甲用户 0-01" })
    .getByRole("button", { name: /用户操作/ })
  await menuButton.focus()
  await page.keyboard.press("Enter")
  await expect(page.getByRole("menuitem", { name: "Delete User" })).toBeHidden()

  // 新页到达后恢复正常可交互；旧行卸载（稳定 id），新行操作可用
  await expect(page.getByText("乙用户 1-00")).toBeVisible({ timeout: 5000 })
  await page
    .locator("tr", { hasText: "乙用户 1-01" })
    .getByRole("button", { name: /用户操作/ })
    .click()
  await expect(
    page.getByRole("menuitem", { name: "Delete User" }),
  ).toBeVisible()
  expect(mock.deleted).toEqual([])
})

test("R13: failed page fetch shows error card with retry, not empty data", async ({
  page,
}) => {
  const mock = await mockAdmin(page)
  await page.goto("/admin")
  await expect(page.getByText("甲用户 0-00")).toBeVisible()

  // 第二页请求持续失败（含 Query 内部重试）直到放行
  mock.failPageUntilAllowed()
  await page.getByRole("button", { name: "下一页" }).click()
  // 失败：错误卡 + 重试入口，而不是「暂无数据」/总数归零
  await expect(page.getByRole("alert")).toBeVisible({ timeout: 20000 })
  await expect(page.getByText("用户列表加载失败")).toBeVisible()
  await expect(page.getByText("暂无数据")).toBeHidden()

  // 放行后重试成功，恢复列表
  mock.allowPage()
  await page.getByRole("button", { name: "重试" }).click()
  await expect(page.getByText("乙用户 1-00")).toBeVisible({ timeout: 5000 })
})
