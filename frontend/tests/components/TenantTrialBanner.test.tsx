import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { ModuleStatus } from "@/client"
import { TenantModuleBanner } from "@/components/Teaching/TenantModuleBanner"
import { I18nProvider } from "@/lib/i18n"

/**
 * 校管后台到期提醒横幅：
 * - 仅 school_admin（兼容旧 admin）可见，teacher / operator 不显示；
 * - active + trial 按 30 / 7 / 1 三档；expired 显示到期文案；
 * - disabled / not_granted / scheduled 不提示；两模块同时命中合并为一条横幅。
 */

function fixture(
  partial: Partial<ModuleStatus> & { module_key: string },
): ModuleStatus {
  return {
    state: "not_granted",
    enabled: false,
    effective_at: null,
    starts_at: null,
    expires_at: null,
    grant_type: "manual",
    days_left: null,
    granted_by: null,
    ...partial,
  }
}

function renderBanner(statuses: ModuleStatus[], role: string | null) {
  return render(
    <I18nProvider>
      <TenantModuleBanner statuses={statuses} role={role} />
    </I18nProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  vi.restoreAllMocks()
})

describe("TenantModuleBanner 角色门禁", () => {
  const expiredSpeaking = [
    fixture({ module_key: "speaking", state: "expired", enabled: true }),
  ]

  it("school_admin 看到到期提醒", () => {
    renderBanner(expiredSpeaking, "school_admin")
    expect(screen.getByTestId("tenant-trial-banner")).toBeInTheDocument()
    expect(
      screen.getByText("口语课已到期，入口已关闭；数据保留，请联系平台续期。"),
    ).toBeInTheDocument()
  })

  it("兼容旧值 admin 角色", () => {
    renderBanner(expiredSpeaking, "admin")
    expect(screen.getByTestId("tenant-trial-banner")).toBeInTheDocument()
  })

  it("teacher 不显示横幅", () => {
    renderBanner(expiredSpeaking, "teacher")
    expect(screen.queryByTestId("tenant-trial-banner")).not.toBeInTheDocument()
  })

  it("operator 不显示横幅", () => {
    renderBanner(expiredSpeaking, "operator")
    expect(screen.queryByTestId("tenant-trial-banner")).not.toBeInTheDocument()
  })
})

describe("TenantModuleBanner 试用档位", () => {
  it("试用剩 30 天：提示档，带续期说明", () => {
    renderBanner(
      [
        fixture({
          module_key: "vocabulary",
          state: "active",
          enabled: true,
          grant_type: "trial",
          days_left: 30,
        }),
      ],
      "school_admin",
    )
    expect(screen.getByText("单词课试用还剩 30 天")).toBeInTheDocument()
    expect(
      screen.getByText("到期后师生入口关闭，数据保留，请联系平台续期。"),
    ).toBeInTheDocument()
    expect(screen.getByTestId("tenant-trial-banner-item")).toHaveAttribute(
      "data-level",
      "trial",
    )
  })

  it("试用剩 7 天：warning 档", () => {
    renderBanner(
      [
        fixture({
          module_key: "speaking",
          state: "active",
          enabled: true,
          grant_type: "trial",
          days_left: 7,
        }),
      ],
      "school_admin",
    )
    expect(screen.getByText("口语课试用还剩 7 天")).toBeInTheDocument()
    expect(screen.getByTestId("tenant-trial-banner-item")).toHaveAttribute(
      "data-level",
      "warning",
    )
  })

  it("试用剩 1 天：critical 档", () => {
    renderBanner(
      [
        fixture({
          module_key: "speaking",
          state: "active",
          enabled: true,
          grant_type: "trial",
          days_left: 1,
        }),
      ],
      "school_admin",
    )
    expect(screen.getByText("口语课试用还剩 1 天")).toBeInTheDocument()
    expect(screen.getByTestId("tenant-trial-banner-item")).toHaveAttribute(
      "data-level",
      "critical",
    )
  })

  it("英文 1 天用单数 day left", () => {
    localStorage.setItem("esa:lang", "en")
    renderBanner(
      [
        fixture({
          module_key: "speaking",
          state: "active",
          enabled: true,
          grant_type: "trial",
          days_left: 1,
        }),
      ],
      "school_admin",
    )
    expect(screen.getByText("Speaking trial: 1 day left")).toBeInTheDocument()
  })

  it("已关闭 / 未开通 / 待生效 / 付费均不提示", () => {
    renderBanner(
      [
        fixture({ module_key: "speaking", state: "disabled", enabled: false }),
        fixture({ module_key: "vocabulary", state: "not_granted" }),
        fixture({
          module_key: "speaking",
          state: "scheduled",
          enabled: true,
        }),
        fixture({
          module_key: "vocabulary",
          state: "active",
          enabled: true,
          grant_type: "paid",
        }),
      ],
      "school_admin",
    )
    expect(screen.queryByTestId("tenant-trial-banner")).not.toBeInTheDocument()
  })

  it("两个模块同时命中：合并在同一横幅内逐行列出", () => {
    renderBanner(
      [
        fixture({ module_key: "speaking", state: "expired", enabled: true }),
        fixture({
          module_key: "vocabulary",
          state: "active",
          enabled: true,
          grant_type: "trial",
          days_left: 5,
        }),
      ],
      "school_admin",
    )
    const items = screen.getAllByTestId("tenant-trial-banner-item")
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveAttribute("data-level", "expired")
    expect(items[1]).toHaveAttribute("data-level", "warning")
    expect(screen.getByText("单词课试用还剩 5 天")).toBeInTheDocument()
  })
})
