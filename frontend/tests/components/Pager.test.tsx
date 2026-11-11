import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { Pager } from "@/components/Common/Pager"
import { I18nProvider } from "@/lib/i18n"

/**
 * Pager 是管理列表的公用分页条。它有三条容易回归的语义：
 * 1. 首页「上一页」禁用、末页「下一页」禁用（避免点到空页）
 * 2. isPlaceholder 期间两个方向都禁用（旧页数据上翻页会错位跳页）
 * 3. 文案里的总数与页数要用服务端 count 算，不能用本地数组长度
 */

function renderPager(props: Partial<Parameters<typeof Pager>[0]> = {}) {
  const onChange = vi.fn()
  render(
    <I18nProvider>
      <Pager
        pageIndex={0}
        pageSize={10}
        count={100}
        onChange={onChange}
        {...props}
      />
    </I18nProvider>,
  )
  return { onChange }
}

beforeEach(() => {
  localStorage.clear()
})

describe("Pager", () => {
  it("按服务端 count 显示总数与总页数", () => {
    renderPager({ pageIndex: 2, pageSize: 10, count: 95 })
    // 95 条 / 每页 10 = 10 页，第三页
    expect(screen.getByText(/共 95 条 · 第 3\/10 页/)).toBeInTheDocument()
  })

  it("count 为 0 时仍显示 1 页，不出现 0/0", () => {
    renderPager({ count: 0 })
    expect(screen.getByText(/共 0 条 · 第 1\/1 页/)).toBeInTheDocument()
  })

  it("第一页禁用上一页，点击不触发翻页", () => {
    const { onChange } = renderPager({ pageIndex: 0 })
    const prev = screen.getByRole("button", { name: /上一页/ })
    expect(prev).toBeDisabled()
    fireEvent.click(prev)
    expect(onChange).not.toHaveBeenCalled()
  })

  it("最后一页禁用下一页", () => {
    // count=20, pageSize=10, pageIndex=1 => 已到末页
    renderPager({ pageIndex: 1, pageSize: 10, count: 20 })
    expect(screen.getByRole("button", { name: /下一页/ })).toBeDisabled()
  })

  it("末页判定用 count 而非页数整除，count=15 时第 2 页就是末页", () => {
    renderPager({ pageIndex: 1, pageSize: 10, count: 15 })
    expect(screen.getByRole("button", { name: /下一页/ })).toBeDisabled()
  })

  it("中间页两个方向都可点，回调收到正确的 pageIndex", () => {
    const { onChange } = renderPager({ pageIndex: 3, pageSize: 10, count: 100 })
    fireEvent.click(screen.getByRole("button", { name: /上一页/ }))
    expect(onChange).toHaveBeenLastCalledWith(2)
    fireEvent.click(screen.getByRole("button", { name: /下一页/ }))
    expect(onChange).toHaveBeenLastCalledWith(4)
  })

  it("isPlaceholder 期间两个方向都禁用，防止旧页数据上误翻页", () => {
    const { onChange } = renderPager({
      pageIndex: 2,
      isPlaceholder: true,
    })
    const prev = screen.getByRole("button", { name: /上一页/ })
    const next = screen.getByRole("button", { name: /下一页/ })
    expect(prev).toBeDisabled()
    expect(next).toBeDisabled()
    fireEvent.click(prev)
    fireEvent.click(next)
    expect(onChange).not.toHaveBeenCalled()
  })

  it("切到英文时文案跟随", () => {
    localStorage.setItem("esa:lang", "en")
    renderPager({ pageIndex: 0, pageSize: 10, count: 30 })
    expect(screen.getByText(/30 items · Page 1\/3/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Previous/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Next/ })).toBeInTheDocument()
  })

  it("分页容器带 aria-label，便于读屏与端到端定位", () => {
    renderPager()
    expect(screen.getByRole("navigation", { name: /分页/ })).toBeInTheDocument()
  })
})
