import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  type VocabularyLeaderboardSettings,
  type VocabularyLeaderboardView,
  VocabularyService,
} from "@/client"
import { LeaderboardTeacherPanel } from "@/components/Teaching/VocabTasks/LeaderboardTeacherPanel"
import { I18nProvider } from "@/lib/i18n"

/**
 * 教师端学习榜面板：
 * - 默认口径仅教师可见、匿名开启；预览表显示参与人数；
 * - 保存 payload 只带 enabled / audience / anonymous，不改学生授权、等级或 XP；
 * - 切换为学生可见后，保存的 audience 为 students。
 */

const DEFAULT_SETTINGS: VocabularyLeaderboardSettings = {
  enabled: true,
  audience: "teachers",
  anonymous: true,
  top_n: 10,
}

function makeBoard(
  overrides: Partial<VocabularyLeaderboardView> = {},
): VocabularyLeaderboardView {
  return {
    week_start: "2026-11-23",
    settings: DEFAULT_SETTINGS,
    entries: [
      { rank: 1, score: 5, alias_no: 7, display_name: null, suffix: null },
    ],
    my_entry: null,
    my_rank: null,
    my_score: 0,
    joined: false,
    participant_count: 5,
    ...overrides,
  }
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <LeaderboardTeacherPanel code="DEMO01" />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

async function clickSaveButton() {
  const button = screen.getByText("保存设置").closest("button")
  if (!button) throw new Error("保存设置按钮未找到")
  await waitFor(() => expect(button).not.toBeDisabled())
  button.click()
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  vi.restoreAllMocks()
})

describe("LeaderboardTeacherPanel", () => {
  it("默认仅教师可见：展示默认提示、参与人数预览与匿名编号", async () => {
    vi.spyOn(VocabularyService, "readLeaderboardSettings").mockResolvedValue(
      DEFAULT_SETTINGS,
    )
    vi.spyOn(VocabularyService, "readLeaderboard").mockResolvedValue(
      makeBoard(),
    )

    renderPanel()

    await waitFor(() => expect(screen.getByText("07")).toBeInTheDocument())
    expect(
      screen.getByText("默认仅教师可见、默认匿名；学生默认不参加。"),
    ).toBeInTheDocument()
    expect(screen.getByText("参与 5 人")).toBeInTheDocument()

    const audienceSelect = screen.getByRole("combobox")
    expect(audienceSelect).toHaveValue("teachers")
  })

  it("保存默认设置：payload 为 enabled / teachers / anonymous", async () => {
    vi.spyOn(VocabularyService, "readLeaderboardSettings").mockResolvedValue(
      DEFAULT_SETTINGS,
    )
    vi.spyOn(VocabularyService, "readLeaderboard").mockResolvedValue(
      makeBoard(),
    )
    const saveSpy = vi
      .spyOn(VocabularyService, "updateLeaderboardSettings")
      .mockResolvedValue(DEFAULT_SETTINGS)

    renderPanel()

    await waitFor(() =>
      expect(screen.getByText("保存设置")).toBeInTheDocument(),
    )
    await clickSaveButton()

    await waitFor(() =>
      expect(saveSpy).toHaveBeenCalledWith({
        code: "DEMO01",
        vocabularyLeaderboardSettingsUpdate: {
          enabled: true,
          audience: "teachers",
          anonymous: true,
        },
      }),
    )
  })

  it("切换为学生可见后保存：payload audience 为 students", async () => {
    vi.spyOn(VocabularyService, "readLeaderboardSettings").mockResolvedValue(
      DEFAULT_SETTINGS,
    )
    vi.spyOn(VocabularyService, "readLeaderboard").mockResolvedValue(
      makeBoard(),
    )
    const saveSpy = vi
      .spyOn(VocabularyService, "updateLeaderboardSettings")
      .mockResolvedValue({ ...DEFAULT_SETTINGS, audience: "students" })

    renderPanel()

    const audienceSelect = screen.getByRole("combobox")
    fireEvent.change(audienceSelect, { target: { value: "students" } })
    await waitFor(() => expect(audienceSelect).toHaveValue("students"))

    await clickSaveButton()

    await waitFor(() =>
      expect(saveSpy).toHaveBeenCalledWith({
        code: "DEMO01",
        vocabularyLeaderboardSettingsUpdate: {
          enabled: true,
          audience: "students",
          anonymous: true,
        },
      }),
    )
  })
})
