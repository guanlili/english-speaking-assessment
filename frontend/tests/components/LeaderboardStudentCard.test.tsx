import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  ApiError,
  type VocabularyLeaderboardView,
  VocabularyService,
} from "@/client"
import { LeaderboardStudentCard } from "@/components/Vocabulary/Leaderboard/LeaderboardStudentCard"
import { I18nProvider } from "@/lib/i18n"

/**
 * 学生首页榜卡：
 * - 未参加：只给加入入口，不显示任何人与人数；
 * - 已参加零分：仍按已参加展示，本人榜外、本周掌握 0 词；
 * - 匿名：只显示「同学 07」编号；
 * - 403 leaderboard_unavailable / 仅教师可见：静默隐藏卡片。
 */

const STUDENT_SETTINGS = {
  enabled: true,
  audience: "students",
  anonymous: true,
  top_n: 10,
}

function makeView(
  overrides: Partial<VocabularyLeaderboardView> = {},
): VocabularyLeaderboardView {
  return {
    week_start: "2026-11-23",
    settings: STUDENT_SETTINGS,
    entries: [],
    my_entry: null,
    my_rank: null,
    my_score: 0,
    joined: false,
    participant_count: null,
    ...overrides,
  }
}

function renderCard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const rootRoute = createRootRoute({
    component: () => <LeaderboardStudentCard code="DEMO01" />,
  })
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/vocab/$code",
    component: () => null,
  })
  const boardRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/vocab/$code/leaderboard",
    component: () => null,
  })
  const routeTree = rootRoute.addChildren([indexRoute, boardRoute])
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/vocab/DEMO01"] }),
  })
  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <RouterProvider router={router} />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  vi.restoreAllMocks()
})

describe("LeaderboardStudentCard", () => {
  it("未参加：显示加入说明与按钮，不显示参与人数", async () => {
    vi.spyOn(VocabularyService, "readLeaderboard").mockResolvedValue(
      makeView({ joined: false, participant_count: null }),
    )
    const joinSpy = vi
      .spyOn(VocabularyService, "updateParticipation")
      .mockResolvedValue({ joined: true, alias_no: 7 })

    renderCard()

    await waitFor(() =>
      expect(screen.getByText("加入榜单")).toBeInTheDocument(),
    )
    expect(
      screen.getByText("自愿参加；未参加不显示任何人，也看不到人数。"),
    ).toBeInTheDocument()
    // 学生视角不下发人数，卡片也不得自行渲染人数
    expect(screen.queryByText(/\d+\s*人/)).not.toBeInTheDocument()

    screen.getByText("加入榜单").closest("button")?.click()
    await waitFor(() =>
      expect(joinSpy).toHaveBeenCalledWith({
        code: "DEMO01",
        vocabularyParticipationUpdate: { joined: true },
      }),
    )
  })

  it("已参加但本周零分：仍显示已参加，本人榜外、掌握 0 词", async () => {
    vi.spyOn(VocabularyService, "readLeaderboard").mockResolvedValue(
      makeView({ joined: true, my_score: 0, my_rank: null, entries: [] }),
    )

    renderCard()

    await waitFor(() =>
      expect(screen.getByText("本周掌握 0 词")).toBeInTheDocument(),
    )
    expect(screen.getByText("榜外")).toBeInTheDocument()
    expect(screen.getByText("本周还没有人完成复习。")).toBeInTheDocument()
    expect(screen.queryByText("加入榜单")).not.toBeInTheDocument()
  })

  it("匿名条目：只渲染两位编号「同学 07」", async () => {
    vi.spyOn(VocabularyService, "readLeaderboard").mockResolvedValue(
      makeView({
        joined: true,
        my_score: 2,
        my_rank: 2,
        entries: [
          {
            rank: 1,
            score: 5,
            alias_no: 7,
            display_name: null,
            suffix: null,
          },
        ],
      }),
    )

    renderCard()

    await waitFor(() => expect(screen.getByText("07")).toBeInTheDocument())
    expect(screen.getByText("同学")).toBeInTheDocument()
    expect(screen.queryByText(/李梨|小红/)).not.toBeInTheDocument()
  })

  it("403 leaderboard_unavailable：静默隐藏，不弹错也不显示空卡", async () => {
    vi.spyOn(VocabularyService, "readLeaderboard").mockRejectedValue(
      new ApiError(403, { detail: "leaderboard_unavailable" }, ""),
    )

    renderCard()

    await waitFor(() =>
      expect(screen.queryByText("班内学习榜")).not.toBeInTheDocument(),
    )
  })

  it("仅教师可见：学生视角不渲染卡片", async () => {
    vi.spyOn(VocabularyService, "readLeaderboard").mockResolvedValue(
      makeView({
        settings: { ...STUDENT_SETTINGS, audience: "teachers" },
      }),
    )

    renderCard()

    await waitFor(() =>
      expect(screen.queryByText("班内学习榜")).not.toBeInTheDocument(),
    )
  })
})
