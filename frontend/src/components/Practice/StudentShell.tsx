import { Link, useParams } from "@tanstack/react-router"
import {
  ChartLine,
  Home,
  ListChecks,
  Map as MapIcon,
  Mic,
  Sparkles,
} from "lucide-react"
import type { ReactNode } from "react"
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
  active: "home" | "practice" | "explore" | "me" | "map"
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
