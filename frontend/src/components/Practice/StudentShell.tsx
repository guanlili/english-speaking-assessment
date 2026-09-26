import { useQuery } from "@tanstack/react-query"
import { Link, useParams } from "@tanstack/react-router"
import {
  Bell,
  ChartLine,
  CircleHelp,
  Home,
  ListChecks,
  Map as MapIcon,
  Mic,
  Sparkles,
  UsersRound,
} from "lucide-react"
import { type ReactNode, useState } from "react"
import { ClassesService } from "@/client"
import { displayName, loadStudent } from "@/lib/classroom-student"

/**
 * 学生端布局（SpeakUp）：左侧导航 + 内容区。
 * 教学工具定位：导航以「今日练习」为首（老师课堂指派），探索与成长为辅。
 */
function StudentShell({
  active,
  children,
  wide,
}: {
  active: "home" | "practice" | "explore" | "me" | "map" | "help" | "classroom"
  children: ReactNode
  wide?: boolean
}) {
  const { code } = useParams({ strict: false })
  const student = code ? loadStudent(code) : null

  const items = [
    { key: "home", to: "/home/$code", label: "学习首页", icon: Home },
    { key: "practice", to: "/p/$code", label: "今日练习", icon: Mic },
    { key: "explore", to: "/explore/$code", label: "主题探索", icon: Sparkles },
    { key: "me", to: "/me/$code", label: "我的成长", icon: ChartLine },
    { key: "map", to: "/map/$code", label: "关卡地图", icon: MapIcon },
    {
      key: "classroom",
      to: "/classroom/$code",
      label: "我的课堂",
      icon: UsersRound,
    },
    { key: "help", to: "/help/$code", label: "帮助与设备", icon: CircleHelp },
  ] as const

  return (
    <div className="flex min-h-screen bg-background">
      {/* 侧边导航（桌面）；移动端折叠为顶部条 */}
      <aside className="sticky top-0 hidden h-screen w-52 shrink-0 flex-col border-r border-border bg-card p-4 md:flex">
        <Link
          to="/home/$code"
          params={{ code: code ?? "" }}
          className="mb-6 flex items-center gap-2 px-2"
        >
          <span className="flex size-9 -rotate-4 items-center justify-center rounded-[13px_13px_13px_4px] bg-primary gap-[3px]">
            <i className="block h-3 w-1 rounded bg-primary-foreground" />
            <i className="block h-5 w-1 rounded bg-primary-foreground" />
            <i className="block h-4 w-1 rounded bg-primary-foreground" />
          </span>
          <span>
            <span className="block text-lg leading-none font-750 tracking-tight">
              SpeakUp<span className="text-primary">.</span>
            </span>
            <span className="block text-[10px] tracking-[0.3em] text-muted-foreground">
              开 口 说
            </span>
          </span>
        </Link>
        <nav className="grid gap-1.5">
          {items.map((item) => (
            <Link
              key={item.key}
              to={item.to}
              params={{ code: code ?? "" }}
              className={
                active === item.key
                  ? "flex min-h-11 items-center gap-3 rounded-xl bg-secondary px-3.5 text-sm font-650 text-primary"
                  : "flex min-h-11 items-center gap-3 rounded-xl px-3.5 text-sm text-muted-foreground transition hover:bg-background hover:text-foreground"
              }
            >
              <item.icon className="size-4" />
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto">
          <NotificationBell code={code ?? ""} />
          <div className="rounded-2xl bg-background p-4">
            <p className="flex items-center gap-1.5 text-xs font-semibold">
              <ListChecks className="size-3.5 text-primary" />
              小小练习，大大进步
            </p>
            <p className="mt-1.5 text-[10px] leading-relaxed text-muted-foreground">
              不必完美表达，先勇敢说出来。
            </p>
          </div>
          {student && (
            <p className="mt-3 truncate px-2 text-[11px] text-muted-foreground">
              {displayName(student)} · 课堂 {code}
            </p>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* 移动端顶条 */}
        <div className="flex items-center gap-2 border-b border-border bg-card px-4 py-2.5 md:hidden">
          {items.map((item) => (
            <Link
              key={item.key}
              to={item.to}
              params={{ code: code ?? "" }}
              className={
                active === item.key
                  ? "rounded-lg bg-secondary p-2 text-primary"
                  : "rounded-lg p-2 text-muted-foreground"
              }
            >
              <item.icon className="size-4" />
            </Link>
          ))}
        </div>
        <main
          className={`page-enter mx-auto w-full flex-1 p-5 md:p-8 ${
            wide ? "max-w-6xl" : "max-w-3xl"
          }`}
        >
          {children}
        </main>
        <footer className="px-6 pb-4 text-center text-[10px] text-muted-foreground">
          SpeakUp · 每一种声音，都值得被听见。
        </footer>
      </div>
    </div>
  )
}

export default StudentShell

function NotificationBell({ code }: { code: string }) {
  const student = loadStudent(code)
  const [open, setOpen] = useState(false)
  const todayQuery = useQuery({
    queryKey: ["classroom", code, "today", student?.id],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    enabled: student !== null && code !== "",
    retry: 1,
    retryDelay: 500,
    staleTime: 60_000,
  })
  const g = todayQuery.data?.gamification
  const done = todayQuery.data
    ? todayQuery.data.attempts.filter(
        (a) => a.status === "done" || a.status === "failed",
      ).length
    : 0
  const total = todayQuery.data?.items.length ?? 5
  const today = new Date().toISOString().slice(0, 10)
  const newBadges = (g?.badges ?? []).filter(
    (b) => (b.awarded_at ?? "").slice(0, 10) === today,
  )

  return (
    <div className="relative mb-3">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label="消息通知"
        className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3.5 text-sm text-muted-foreground transition hover:bg-background hover:text-foreground"
      >
        <Bell className="size-4" />
        消息
        {newBadges.length > 0 && (
          <span className="ml-auto size-2 rounded-full bg-orange-400" />
        )}
      </button>
      {open && (
        <div className="absolute bottom-full left-0 z-30 mb-2 w-64 rounded-2xl border border-border bg-card p-4 shadow-lg">
          <p className="mb-2 text-xs font-semibold">学习空间的消息</p>
          <div className="space-y-3 text-xs">
            <div className="border-b border-border pb-3">
              <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                今日任务
              </span>
              <p className="mt-1.5 font-medium">
                {done >= total
                  ? "今天的练习已完成，辛苦啦"
                  : `已完成 ${done}/${total} 题`}
              </p>
              <p className="mt-0.5 text-muted-foreground">
                {done >= total
                  ? "可以去主题探索里自由聊一个话题"
                  : "回来继续，每题只占用一点时间"}
              </p>
            </div>
            {g && (g.streak_days ?? 0) > 0 && (
              <div className="border-b border-border pb-3">
                <span className="rounded bg-accent px-1.5 py-0.5 text-[10px] font-semibold text-accent-foreground">
                  一点鼓励
                </span>
                <p className="mt-1.5 font-medium">
                  你已经坚持练习 {g.streak_days ?? 0} 天
                </p>
                <p className="mt-0.5 text-muted-foreground">
                  一步一步来，就很好。
                </p>
              </div>
            )}
            {newBadges.length > 0 && (
              <div>
                <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                  新徽章
                </span>
                <p className="mt-1.5 font-medium">
                  {newBadges.map((b) => b.label).join("、")}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
