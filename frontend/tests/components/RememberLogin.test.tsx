import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { RememberLogin } from "@/components/Common/RememberLogin"
import { I18nProvider } from "@/lib/i18n"

/**
 * 「7 天内免登录」是三处登录入口共用的安全开关。
 * 它的价值在文案与默认语义：默认会话 24 小时，勾选才延长到 7 天，
 * 并且必须提醒用户在公用电脑上不要勾。文案丢了或语义反了都是安全问题。
 */

function renderRemember(
  overrides: Partial<Parameters<typeof RememberLogin>[0]> = {},
) {
  const onCheckedChange = vi.fn()
  render(
    <I18nProvider>
      <RememberLogin
        checked={false}
        onCheckedChange={onCheckedChange}
        disabled={false}
        {...overrides}
      />
    </I18nProvider>,
  )
  return { onCheckedChange }
}

beforeEach(() => {
  localStorage.clear()
})

describe("RememberLogin", () => {
  it("默认状态：文案同时说明「7 天免登录」与「默认 24 小时」", () => {
    renderRemember()
    expect(screen.getByText("7 天内免登录")).toBeInTheDocument()
    // 默认期限必须写出来，否则用户会误以为默认就是长期登录
    expect(screen.getByText(/默认登录状态 24 小时后失效/)).toBeInTheDocument()
  })

  it("明确提醒公用电脑不要勾选", () => {
    renderRemember()
    expect(screen.getByText(/公用电脑请不要勾选/)).toBeInTheDocument()
  })

  it("勾选时回调 true", () => {
    const { onCheckedChange } = renderRemember()
    fireEvent.click(screen.getByRole("checkbox"))
    expect(onCheckedChange).toHaveBeenCalledWith(true)
  })

  it("已勾选状态下再次点击回调 false（可取消）", () => {
    const { onCheckedChange } = renderRemember({ checked: true })
    fireEvent.click(screen.getByRole("checkbox"))
    expect(onCheckedChange).toHaveBeenCalledWith(false)
  })

  it("disabled 时不可点击，不产生回调", () => {
    const { onCheckedChange } = renderRemember({ disabled: true })
    const box = screen.getByRole("checkbox")
    expect(box).toBeDisabled()
    fireEvent.click(box)
    expect(onCheckedChange).not.toHaveBeenCalled()
  })

  it("label 与 checkbox 通过 id/htmlFor 绑定，点文字也能切换", () => {
    const { onCheckedChange } = renderRemember()
    fireEvent.click(screen.getByText("7 天内免登录"))
    expect(onCheckedChange).toHaveBeenCalled()
  })

  it("英文环境文案同步切换", () => {
    localStorage.setItem("esa:lang", "en")
    renderRemember()
    expect(screen.getByText("Keep me signed in for 7 days")).toBeInTheDocument()
    expect(
      screen.getByText(/Don't tick this on a shared computer/),
    ).toBeInTheDocument()
  })

  it("透传 testId，便于端到端定位", () => {
    renderRemember({ testId: "remember-login" })
    expect(screen.getByTestId("remember-login")).toBeInTheDocument()
  })
})
