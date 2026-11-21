import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ClassesService, type ClassroomTeacherPublic } from "@/client"
import { TeacherTeamCard } from "@/components/Teaching/TeacherTeamCard"
import { I18nProvider } from "@/lib/i18n"

/**
 * 教师团队入口：主教师看到添加区与移除入口，共管教师只看到自己的退出入口；
 * 真正的权限仍由服务端 membership 判定（见后端 test_classroom_teachers）。
 */

const TEAM: ClassroomTeacherPublic[] = [
  {
    user_id: "owner-1",
    full_name: "王老师",
    email: "wang@example.com",
    role: "owner",
    is_me: false,
  },
  {
    user_id: "co-1",
    full_name: "李老师",
    email: "li@example.com",
    role: "co_teacher",
    is_me: true,
  },
]

function renderCard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <TeacherTeamCard code="DEMO01" />
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

describe("TeacherTeamCard", () => {
  it("共管教师只能退出自己，不显示添加区", async () => {
    vi.spyOn(ClassesService, "listClassTeachers").mockResolvedValue(TEAM)
    renderCard()
    await waitFor(() => expect(screen.getByText("王老师")).toBeInTheDocument())
    expect(screen.getByText("主教师")).toBeInTheDocument()
    expect(screen.getByText("共管教师")).toBeInTheDocument()
    expect(screen.getByText("退出共管")).toBeInTheDocument()
    expect(screen.queryByText("添加共管教师")).not.toBeInTheDocument()
    expect(screen.queryByText("移除")).not.toBeInTheDocument()
  })

  it("主教师看到添加区与移除他人入口", async () => {
    vi.spyOn(ClassesService, "listClassTeachers").mockResolvedValue([
      { ...TEAM[0], is_me: true },
      { ...TEAM[1], is_me: false },
    ])
    vi.spyOn(ClassesService, "teacherCandidates").mockResolvedValue([])
    renderCard()
    await waitFor(() => expect(screen.getByText("王老师")).toBeInTheDocument())
    expect(screen.getByText("添加共管教师")).toBeInTheDocument()
    expect(screen.getByText("移除")).toBeInTheDocument()
  })
})
