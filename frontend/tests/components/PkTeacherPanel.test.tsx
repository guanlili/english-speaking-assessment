import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  type PkLobbyView,
  type VocabularyBookDetail,
  VocabularyService,
} from "@/client"
import { PkTeacherPanel } from "@/components/Teaching/VocabTasks/PkTeacherPanel"
import { I18nProvider } from "@/lib/i18n"

/**
 * 教师端 PK 大厅面板：大厅快照派生等待名单与对局分组比分；
 * 教师只轮询大厅，不订阅对局 SSE（教师不在对局名单内，订阅会 403）。
 */

const BOOKS: VocabularyBookDetail[] = [
  { id: "b1", title: "Unit 1", scope: "class", status: "active" },
] as VocabularyBookDetail[]

const OPEN_LOBBY: PkLobbyView = {
  lobby_id: "l1",
  status: "open",
  book_id: "b1",
  question_count: 8,
  per_question_seconds: 20,
  queue_count: 1,
  active_match_count: 1,
  players: [
    {
      student_id: "s1",
      display_name: "小明",
      status: "waiting",
      score: 0,
      answered_count: 0,
      correct_count: 0,
      total_seconds: 0,
      match_id: null,
    },
    {
      student_id: "s2",
      display_name: "小红",
      status: "active",
      side: "left",
      score: 120,
      answered_count: 3,
      correct_count: 3,
      total_seconds: 12,
      match_id: "m1",
    },
    {
      student_id: "s3",
      display_name: "小刚",
      status: "active",
      side: "right",
      score: 90,
      answered_count: 2,
      correct_count: 2,
      total_seconds: 15,
      match_id: "m1",
    },
  ],
}

const CLOSED_LOBBY: PkLobbyView = {
  lobby_id: "l0",
  status: "closed",
  players: [],
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <PkTeacherPanel code="DEMO01" />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  localStorage.setItem("esa:role", "teacher")
  vi.restoreAllMocks()
})

describe("PkTeacherPanel", () => {
  it("开放大厅：展示等待玩家与进行中对局比分，表单锁定并出现关厅按钮", async () => {
    vi.spyOn(VocabularyService, "readPkLobby").mockResolvedValue(OPEN_LOBBY)
    vi.spyOn(VocabularyService, "listBooks").mockResolvedValue(BOOKS)

    renderPanel()

    await waitFor(() => expect(screen.getByText("小明")).toBeInTheDocument())
    expect(screen.getByText("小红")).toBeInTheDocument()
    expect(screen.getByText("小刚")).toBeInTheDocument()
    // 对局比分
    expect(screen.getByText("120")).toBeInTheDocument()
    expect(screen.getByText("90")).toBeInTheDocument()
    // 开放中状态 + 关厅按钮；开启按钮不出现
    expect(screen.getByText("开放中")).toBeInTheDocument()
    expect(screen.getByText("关闭大厅")).toBeInTheDocument()
    expect(screen.queryByText("开启大厅")).not.toBeInTheDocument()
    // 开启期间配置表单锁定
    expect(screen.getByRole("combobox")).toBeDisabled()
  })

  it("关闭大厅：展示开厅按钮，未选词库时不可开启", async () => {
    vi.spyOn(VocabularyService, "readPkLobby").mockResolvedValue(CLOSED_LOBBY)
    vi.spyOn(VocabularyService, "listBooks").mockResolvedValue(BOOKS)

    renderPanel()

    await waitFor(() =>
      expect(screen.getByText("开启大厅")).toBeInTheDocument(),
    )
    const openButton = screen.getByText("开启大厅").closest("button")
    expect(openButton).toBeDisabled()
    expect(screen.getByText("未开放")).toBeInTheDocument()
  })
})
