import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import { I18nProvider } from "@/lib/i18n"

/**
 * ConfirmDialog 是所有破坏性操作（删篇目 / 停用课堂 / 删环境）的唯一闸门。
 * 它有三条必须成立的语义：
 * 1. 确认期间不能再被关闭（否则「点了确认又点了取消」会留下孤儿请求）
 * 2. onConfirm 抛错时必须保持打开，让用户重试，而不是静默关掉当作成功
 * 3. 成功后才关闭
 */

function renderDialog(
  overrides: Partial<Parameters<typeof ConfirmDialog>[0]> = {},
) {
  const onOpenChange = overrides.onOpenChange ?? vi.fn()
  // 关键：overrides 里的 onConfirm 必须被返回，否则断言的是没被组件使用的那个 mock
  const onConfirm = overrides.onConfirm ?? vi.fn()
  render(
    <I18nProvider>
      <ConfirmDialog
        open
        title="删除情境"
        description="该情境下的录音将一并删除，且不可恢复。"
        onOpenChange={onOpenChange}
        onConfirm={onConfirm}
        {...overrides}
      />
    </I18nProvider>,
  )
  return { onOpenChange, onConfirm }
}

beforeEach(() => {
  localStorage.clear()
})

describe("ConfirmDialog", () => {
  it("渲染标题与描述，让用户知道自己在确认什么", () => {
    renderDialog()
    expect(screen.getByText("删除情境")).toBeInTheDocument()
    expect(screen.getByText(/该情境下的录音将一并删除/)).toBeInTheDocument()
  })

  it("默认按钮文案是中英双语可切换的", () => {
    renderDialog()
    expect(screen.getByRole("button", { name: "确认" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument()
  })

  it("英文环境下默认文案切换为 Confirm / Cancel", () => {
    localStorage.setItem("esa:lang", "en")
    renderDialog()
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument()
  })

  it("点击取消回传 false，且不触发 onConfirm", () => {
    const { onOpenChange, onConfirm } = renderDialog()
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it("确认成功后先执行 onConfirm，再关闭对话框", async () => {
    const { onOpenChange, onConfirm } = renderDialog({
      onConfirm: vi.fn().mockResolvedValue(undefined),
    })
    fireEvent.click(screen.getByRole("button", { name: "确认" }))
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it("onConfirm 抛错时保持打开，不静默当作成功", async () => {
    const { onOpenChange, onConfirm } = renderDialog({
      onConfirm: vi.fn().mockRejectedValue(new Error("500")),
    })
    fireEvent.click(screen.getByRole("button", { name: "确认" }))
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1))
    // 失败不关闭：调用者的 mutation 负责展示错误，用户可原地重试
    expect(onOpenChange).not.toHaveBeenCalledWith(false)
  })

  it("确认进行中时取消按钮禁用，防止请求悬空", async () => {
    let release: (() => void) | undefined
    const pendingConfirm = new Promise<void>((resolve) => {
      release = resolve
    })
    renderDialog({ onConfirm: () => pendingConfirm })
    fireEvent.click(screen.getByRole("button", { name: "确认" }))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "取消" })).toBeDisabled(),
    )
    release?.()
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "取消" })).not.toBeDisabled(),
    )
  })

  it("确认进行中时 Esc / 遮罩关闭被拦截", async () => {
    let release: (() => void) | undefined
    const pendingConfirm = new Promise<void>((resolve) => {
      release = resolve
    })
    const { onOpenChange } = renderDialog({ onConfirm: () => pendingConfirm })
    fireEvent.click(screen.getByRole("button", { name: "确认" }))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "取消" })).toBeDisabled(),
    )
    fireEvent.keyDown(document.body, { key: "Escape" })
    expect(onOpenChange).not.toHaveBeenCalledWith(false)
    // 释放挂起的 onConfirm：组件会在这之后 setPending(false) 并关闭，
    // 必须包在 act 里，否则产生 act(...) 警告（测试仍会通过但日志被污染）
    await act(async () => {
      release?.()
    })
  })

  it("自定义 confirmText 生效（如「确认停用」而非泛化的「确认」）", () => {
    renderDialog({ confirmText: "确认停用" })
    expect(screen.getByRole("button", { name: "确认停用" })).toBeInTheDocument()
  })
})
