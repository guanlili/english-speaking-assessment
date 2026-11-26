import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { type PkLobbyView, type PkMatchView, VocabularyService } from "@/client"
import PkArena from "@/components/Vocabulary/Pk/PkArena"
import { I18nProvider } from "@/lib/i18n"

/**
 * 学生侧 PkArena 挂载与降级路径：
 * - 无对局时只拉大厅快照，不建立 SSE；
 * - 已在对局但 SSE 建连失败/断流时，不抛崩溃，对局快照由轮询兜底展示。
 */

const CLOSED_LOBBY: PkLobbyView = {
  lobby_id: "l0",
  status: "closed",
  players: [],
}

const ACTIVE_LOBBY: PkLobbyView = {
  lobby_id: "l1",
  status: "open",
  my_status: "active",
  my_match_id: "m1",
  players: [
    {
      student_id: "s1",
      display_name: "我",
      status: "active",
      side: "left",
      score: 60,
      answered_count: 1,
      correct_count: 1,
      total_seconds: 5,
      match_id: "m1",
    },
    {
      student_id: "s2",
      display_name: "对手",
      status: "active",
      side: "right",
      score: 40,
      answered_count: 1,
      correct_count: 1,
      total_seconds: 6,
      match_id: "m1",
    },
  ],
}

const ACTIVE_MATCH: PkMatchView = {
  match_id: "m1",
  lobby_id: "l1",
  status: "active",
  state_version: 1,
  question_count: 3,
  current_item_index: 0,
  remaining_seconds: 20,
  per_question_seconds: 20,
  me: ACTIVE_LOBBY.players![0],
  opponent: ACTIVE_LOBBY.players![1],
  items: [],
  result: null,
}

function renderArena() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <PkArena code="DEMO01" />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  localStorage.setItem("esa:role", "student")
  vi.restoreAllMocks()
  // SSE 通道模拟建连失败：裸 fetch 拒绝，交由轮询兜底
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("sse unavailable")),
  )
})

describe("PkArena", () => {
  it("关闭大厅：正常挂载，不建立 SSE 连接", async () => {
    vi.spyOn(VocabularyService, "readPkLobby").mockResolvedValue(CLOSED_LOBBY)

    renderArena()

    await waitFor(() =>
      expect(screen.getByText("当前大厅已关闭。")).toBeInTheDocument(),
    )
    expect(screen.getByText("课堂对战 PK")).toBeInTheDocument()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it("en_zh 题面显示英文单词，而不是中文释义", async () => {
    const matchWithPrompt: PkMatchView = {
      ...ACTIVE_MATCH,
      items: [
        {
          item_index: 0,
          prompt_type: "en_zh",
          headword: "apple",
          meaning_zh: "苹果",
          choices: [
            { word_id: "w1", headword: "apple", meaning_zh: "苹果" },
            { word_id: "w2", headword: "banana", meaning_zh: "香蕉" },
          ],
        },
      ],
    }
    vi.spyOn(VocabularyService, "readPkLobby").mockResolvedValue(ACTIVE_LOBBY)
    vi.spyOn(VocabularyService, "readPkMatchState").mockResolvedValue(
      matchWithPrompt,
    )

    renderArena()

    await waitFor(() =>
      expect(screen.getByTestId("pk-prompt")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("pk-prompt")).toHaveTextContent("apple")
    expect(screen.getByTestId("pk-prompt")).not.toHaveTextContent("苹果")
  })

  it("SSE 不可用：对局快照仍由轮询兜底展示，挂载不崩溃", async () => {
    vi.spyOn(VocabularyService, "readPkLobby").mockResolvedValue(ACTIVE_LOBBY)
    vi.spyOn(VocabularyService, "readPkMatchState").mockResolvedValue(
      ACTIVE_MATCH,
    )

    renderArena()

    await waitFor(() =>
      expect(screen.getByText("对战对局")).toBeInTheDocument(),
    )
    expect(screen.getByText("60")).toBeInTheDocument()
    expect(screen.getByText("40")).toBeInTheDocument()
    // 确实尝试过订阅对局事件流；失败后走降级，而不是把页面打崩
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/matches/m1/events"),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: expect.any(String) }),
      }),
    )
  })

  it("对局快照未就绪时不提前挂载面板；快照到达后再渲染（D11 就绪态）", async () => {
    vi.spyOn(VocabularyService, "readPkLobby").mockResolvedValue(ACTIVE_LOBBY)
    let resolveMatch: (value: PkMatchView) => void = () => undefined
    const matchSpy = vi
      .spyOn(VocabularyService, "readPkMatchState")
      .mockImplementation(
        () =>
          new Promise<PkMatchView>((resolve) => {
            resolveMatch = resolve
          }),
      )

    renderArena()

    // 首帧对局快照在途：不提前渲染空面板/拼写输入框
    await waitFor(() => expect(screen.getByText("PK 大厅")).toBeInTheDocument())
    expect(screen.queryByText("对战对局")).not.toBeInTheDocument()
    await waitFor(() => expect(matchSpy).toHaveBeenCalled())

    resolveMatch(ACTIVE_MATCH)
    await waitFor(() =>
      expect(screen.getByText("对战对局")).toBeInTheDocument(),
    )
  })
})
