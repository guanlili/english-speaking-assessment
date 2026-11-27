import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { type FarmView, VocabularyService } from "@/client"
import FarmPanel from "@/components/Vocabulary/Farm/FarmPanel"
import { I18nProvider } from "@/lib/i18n"

/**
 * 专注农场面板三态展示：
 * - 未成熟：收获按钮禁用，提示还差几点；
 * - 成熟可收获：按钮可用并标注 +10 XP；
 * - 今日 XP 满额：按钮禁用并提示次日再来。
 * XP / streak / 徽章来源都来自既有课堂账本，组件不本地累加积分。
 */

const BASE_VIEW: FarmView = {
  stage: 1,
  stage_thresholds: [0, 5, 12, 20],
  growth_points: 7,
  points_to_mature: 13,
  ready_to_harvest: false,
  today_points: 3,
  daily_growth_cap: 30,
  xp: 42,
  streak_days: 2,
  harvest_count: 1,
  today_farm_xp: 0,
  farm_xp_daily_cap: 10,
  can_harvest: false,
  badges: [
    {
      key: "streak_3",
      label: "三连胜",
      description: "连续 3 天完成练习",
      awarded_at: null,
      source: "课堂档案/每日计划",
    },
    {
      key: "farm_first_harvest",
      label: "首次收获",
      description: "第一次收获成熟的作物",
      awarded_at: null,
      source: "专注农场",
    },
  ],
  last_harvested_at: null,
}

function renderPanel(view: FarmView) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  vi.spyOn(VocabularyService, "readFarm").mockResolvedValue(view)
  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <FarmPanel code="DEMO01" />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  vi.restoreAllMocks()
})

describe("FarmPanel", () => {
  it("未成熟：收获按钮禁用，展示今日有效练习与既有账本数据", async () => {
    renderPanel(BASE_VIEW)

    expect(await screen.findByText("发芽")).toBeInTheDocument()
    expect(screen.getByText("3 / 30")).toBeInTheDocument()
    expect(screen.getByText("42")).toBeInTheDocument()
    expect(screen.getByText("2 天")).toBeInTheDocument()

    const button = screen.getByRole("button")
    expect(button).toBeDisabled()
    expect(within(button).getByText(/还差 13 点成熟/)).toBeInTheDocument()
  })

  it("成熟可收获：按钮可用并标注 +10 XP", async () => {
    renderPanel({
      ...BASE_VIEW,
      stage: 3,
      growth_points: 20,
      points_to_mature: 0,
      ready_to_harvest: true,
      can_harvest: true,
    })

    expect(await screen.findByText("成熟")).toBeInTheDocument()
    const button = screen.getByRole("button", { name: /\+10 XP/ })
    expect(button).toBeEnabled()
  })

  it("成熟态真实点击收获按钮：调用 harvestFarm 并刷新农场快照", async () => {
    const harvest = vi
      .spyOn(VocabularyService, "harvestFarm")
      .mockResolvedValue({ harvested: true, xp_gained: 10 })
    renderPanel({
      ...BASE_VIEW,
      stage: 3,
      growth_points: 20,
      points_to_mature: 0,
      ready_to_harvest: true,
      can_harvest: true,
    })

    const button = await screen.findByRole("button", { name: /\+10 XP/ })
    await button.click()
    expect(harvest).toHaveBeenCalledTimes(1)
  })

  it("英文界面：收获按钮文案随语言切换为 Harvest", async () => {
    localStorage.setItem("esa:lang", "en")
    renderPanel({
      ...BASE_VIEW,
      stage: 3,
      growth_points: 20,
      points_to_mature: 0,
      ready_to_harvest: true,
      can_harvest: true,
    })

    const button = await screen.findByRole("button", {
      name: /Harvest · \+10 XP/,
    })
    expect(button).toBeEnabled()
  })

  it("今日农场 XP 满额：按钮禁用并提示次日再来", async () => {
    renderPanel({
      ...BASE_VIEW,
      stage: 3,
      growth_points: 20,
      points_to_mature: 0,
      ready_to_harvest: true,
      today_farm_xp: 10,
      can_harvest: false,
    })

    expect(await screen.findByText("成熟")).toBeInTheDocument()
    const button = screen.getByRole("button", { name: /今日农场 XP 已达上限/ })
    expect(button).toBeDisabled()
    expect(
      screen.getByText("今日农场 XP 已达上限，明天再来收获。"),
    ).toBeInTheDocument()
  })

  it("徽章按来源标注：课堂档案与专注农场分开显示", async () => {
    renderPanel(BASE_VIEW)

    expect(await screen.findByText("三连胜")).toBeInTheDocument()
    expect(screen.getByText("首次收获")).toBeInTheDocument()
    const classroomBadge = screen.getByText("三连胜").closest("li")
    const farmBadge = screen.getByText("首次收获").closest("li")
    expect(classroomBadge).not.toBeNull()
    expect(farmBadge).not.toBeNull()
    expect(
      within(classroomBadge!).getByText("课堂档案/每日计划"),
    ).toBeInTheDocument()
    expect(within(farmBadge!).getByText("专注农场")).toBeInTheDocument()
  })
})
