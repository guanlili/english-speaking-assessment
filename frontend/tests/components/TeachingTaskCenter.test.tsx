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

import { ClassesService, ModulesService, VocabularyService } from "@/client"
import { TeachingTaskCenter } from "@/components/Teaching/TeachingTaskCenter"
import { I18nProvider } from "@/lib/i18n"

/**
 * 教师端「教学任务中心」：一个班、多门课。
 * 口径：课程是否出现由已开通课程决定；单门课取数失败只降级该格，不拖垮整页。
 */
function renderCenter() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const rootRoute = createRootRoute({
    component: () => <TeachingTaskCenter />,
  })
  const routes = [
    createRoute({
      getParentRoute: () => rootRoute,
      path: "/classrooms",
      component: () => null,
    }),
    createRoute({
      getParentRoute: () => rootRoute,
      path: "/t/$code",
      component: () => null,
    }),
    createRoute({
      getParentRoute: () => rootRoute,
      path: "/t/$code/vocab",
      component: () => null,
    }),
  ]
  const router = createRouter({
    routeTree: rootRoute.addChildren(routes),
    history: createMemoryHistory({ initialEntries: ["/tasks"] }),
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <RouterProvider router={router} />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

const classroom = {
  id: "c1",
  code: "DEMO01",
  name: "测试班",
  grade: "七年级",
  class_size: 2,
  status: "active",
  created_at: "2026-11-01T00:00:00Z",
} as never

function mockClasses() {
  vi.spyOn(ClassesService, "listMyClassrooms").mockResolvedValue([classroom])
}

function mockBoard() {
  vi.spyOn(ClassesService, "readClassBoard").mockResolvedValue({
    classroom_code: "DEMO01",
    classroom_name: "测试班",
    class_size: 2,
    submitted_count: 1,
    completed_count: 1,
    pending_count: 1,
    students: [
      { student_id: "s1", display_name: "甲", done_count: 3, total_count: 3 },
      { student_id: "s2", display_name: "乙", done_count: 0, total_count: 3 },
    ],
    items: [],
    assignment: { unit_id: "u1", title: "Unit 3 朗读与复述" },
  } as never)
}

function mockModules(modules: string[]) {
  vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
    modules,
    statuses: [],
  } as never)
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  localStorage.setItem("access_token", "mock-token")
  localStorage.setItem("esa:role", "teacher")
  vi.restoreAllMocks()
})

describe("教师端教学任务中心", () => {
  it("双开：一个班同时展示口语课与单词课进展", async () => {
    mockModules(["speaking", "vocabulary"])
    mockClasses()
    mockBoard()
    vi.spyOn(VocabularyService, "listAssignments").mockResolvedValue([
      {
        assignment: {
          id: "a1",
          title: "Day 1 词义与填空",
          status: "published",
          mode: "practice",
          prompt_types: ["meaning"],
          word_count: 10,
        },
        target_count: 2,
        completed_count: 1,
        in_progress_count: 1,
        not_started_count: 0,
        overdue_count: 0,
      },
    ] as never)

    renderCenter()

    await waitFor(() => expect(screen.getByText("测试班")).toBeInTheDocument())
    expect(await screen.findByText("Unit 3 朗读与复述")).toBeInTheDocument()
    expect(await screen.findByText("Day 1 词义与填空")).toBeInTheDocument()
    expect(screen.getByText("已完成 1 / 2")).toBeInTheDocument()
    expect(screen.getByText(/1 个任务进行中 · 最新 1 \/ 2/)).toBeInTheDocument()
  })

  it("只开口语：单词课整列不出现，也不请求词汇任务列表", async () => {
    mockModules(["speaking"])
    mockClasses()
    mockBoard()
    const vocabSpy = vi.spyOn(VocabularyService, "listAssignments")

    renderCenter()

    await waitFor(() => expect(screen.getByText("口语课")).toBeInTheDocument())
    expect(screen.queryByText("单词课")).not.toBeInTheDocument()
    expect(vocabSpy).not.toHaveBeenCalled()
  })

  it("单词课取数失败：该格降级为「—」，口语课照常展示", async () => {
    mockModules(["speaking", "vocabulary"])
    mockClasses()
    mockBoard()
    vi.spyOn(VocabularyService, "listAssignments").mockRejectedValue(
      new Error("boom"),
    )

    renderCenter()

    expect(await screen.findByText("Unit 3 朗读与复述")).toBeInTheDocument()
    expect(
      await screen.findByText("单词课", {}, { timeout: 3000 }),
    ).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText("—").length).toBe(1))
  })
})
