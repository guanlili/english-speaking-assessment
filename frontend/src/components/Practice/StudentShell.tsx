import { useQuery } from "@tanstack/react-query"
import { Link, useParams } from "@tanstack/react-router"
import {
  ArrowRight,
  AudioLines,
  Bell,
  ChartLine,
  ChevronDown,
  CircleHelp,
  Home,
  KeyRound,
  LogOut,
  Mic,
  Sparkles,
  UsersRound,
} from "lucide-react"
import type { ReactNode } from "react"
import { ClassesService } from "@/client"
import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { displayName, loadStudent } from "@/lib/classroom-student"
import { cn } from "@/lib/utils"

const items = [
  { key: "home", to: "/home/$code", label: "学习首页", icon: Home },
  { key: "practice", to: "/p/$code", label: "今日练习", icon: Mic },
  { key: "explore", to: "/explore/$code", label: "主题探索", icon: Sparkles },
  { key: "me", to: "/me/$code", label: "我的成长", icon: ChartLine },
  {
    key: "classroom",
    to: "/classroom/$code",
    label: "我的课堂",
    icon: UsersRound,
  },
  { key: "help", to: "/help/$code", label: "帮助与设备", icon: CircleHelp },
] as const

function StudentShell({
  active,
  children,
  wide,
}: {
  active: (typeof items)[number]["key"]
  children: ReactNode
  wide?: boolean
}) {
  const { code = "" } = useParams({ strict: false })
  const student = loadStudent(code)
  const name = student ? displayName(student) : "学习空间"
  const current = items.find((item) => item.key === active)

  return (
    <div className="flex min-h-svh bg-background">
      <a href="#student-content" className="skip-link">
        跳到主要内容
      </a>
      <aside className="sticky top-0 hidden h-svh w-60 shrink-0 flex-col overflow-y-auto border-r border-border/70 bg-card px-4 py-7 md:flex lg:w-64 lg:px-5">
        <Link to="/home/$code" params={{ code }} className="mb-10 px-2">
          <Logo asLink={false} />
        </Link>
        <p className="mb-3 px-3 text-[10px] font-semibold tracking-[0.18em] text-muted-foreground">
          MY LEARNING SPACE
        </p>
        <nav aria-label="学习导航" className="grid gap-1.5">
          {items.map((item, index) => (
            <Link
              key={item.key}
              aria-current={active === item.key ? "page" : undefined}
              to={item.to}
              params={{ code }}
              className={cn(
                "group flex min-h-12 items-center gap-3 rounded-xl px-3.5 text-sm transition-colors",
                index === 4 && "mt-6",
                active === item.key
                  ? "bg-primary font-semibold text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-secondary/70 hover:text-foreground",
              )}
            >
              <item.icon className="size-[18px]" />
              {item.label}
              {active === item.key && (
                <span className="ml-auto size-1.5 rounded-full bg-current" />
              )}
            </Link>
          ))}
        </nav>
        <div className="mt-auto pt-8">
          <div className="relative overflow-hidden rounded-2xl border border-primary/10 bg-secondary/60 p-4">
            <AudioLines
              className="mb-4 size-6 text-primary"
              aria-hidden="true"
            />
            <p className="font-serif text-xl italic text-primary">
              A little, every day.
            </p>
            <p className="mt-2 text-xs leading-6 text-muted-foreground">
              不必完美表达，先勇敢说出来。
            </p>
          </div>
          <Link
            to="/classroom/$code"
            params={{ code }}
            className="mt-4 flex items-center gap-3 rounded-xl px-3 py-3 transition-colors hover:bg-secondary/60"
          >
            <span className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-sm font-semibold text-accent-foreground">
              {name.slice(0, 1)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">
                {name}
              </span>
              <span className="block text-[11px] text-muted-foreground">
                我的课堂 · {code}
              </span>
            </span>
            <ArrowRight className="size-3.5 text-muted-foreground" />
          </Link>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col pb-20 md:pb-0">
        <header className="sticky top-0 z-20 flex h-[72px] shrink-0 items-center justify-between gap-3 border-b border-border/60 bg-background/95 px-4 backdrop-blur-md sm:px-6 lg:px-9">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              to="/home/$code"
              params={{ code }}
              className="md:hidden"
              aria-label="学习首页"
            >
              <Logo variant="icon" asLink={false} />
            </Link>
            <div>
              <p className="hidden text-[10px] tracking-[0.14em] text-muted-foreground md:block">
                SPEAKUP / 学习空间
              </p>
              <p className="whitespace-nowrap text-sm font-semibold md:mt-1">
                {current?.label}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5 sm:gap-3">
            <Link
              to="/classroom/$code"
              params={{ code }}
              className="hidden items-center gap-2 rounded-full border border-border/80 bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 sm:flex"
            >
              <UsersRound className="size-3.5" /> 课堂 {code}
            </Link>
            <NotificationBell code={code} />
            <Appearance />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  className="gap-1.5 px-1.5 sm:px-2"
                  aria-label="学生账户菜单"
                >
                  <span className="grid size-8 place-items-center rounded-full bg-secondary text-xs font-semibold text-primary">
                    {name.slice(0, 1)}
                  </span>
                  <ChevronDown className="size-3 text-muted-foreground" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56 rounded-2xl p-2">
                <DropdownMenuLabel className="truncate">
                  {name}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {items.slice(4).map((item) => (
                  <DropdownMenuItem key={item.key} asChild>
                    <Link to={item.to} params={{ code }}>
                      <item.icon />
                      {item.label}
                    </Link>
                  </DropdownMenuItem>
                ))}
                <DropdownMenuItem asChild>
                  <a href="/change-password">
                    <KeyRound />
                    修改密码
                  </a>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" asChild>
                  <a
                    href="/login"
                    onClick={() => {
                      localStorage.removeItem("access_token")
                      localStorage.removeItem("esa:role")
                      localStorage.removeItem("esa:must-change-pw")
                      for (const key of Object.keys(localStorage)) {
                        if (key.startsWith("esa:student:"))
                          localStorage.removeItem(key)
                      }
                    }}
                  >
                    <LogOut />
                    退出登录
                  </a>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <main
          id="student-content"
          tabIndex={-1}
          className={cn(
            "page-enter mx-auto w-full flex-1 px-4 py-6 outline-none sm:px-6 md:py-8 lg:px-9",
            wide ? "max-w-7xl" : "max-w-4xl",
          )}
        >
          {children}
        </main>
        <footer className="px-6 pb-6 pt-4 text-center text-[11px] tracking-wide text-muted-foreground">
          SpeakUp · 每一种声音，都值得被听见。
        </footer>
      </div>
      <nav
        aria-label="手机学习导航"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-border/80 bg-card/95 px-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur-md md:hidden"
      >
        {items.slice(0, 4).map((item) => (
          <Link
            key={item.key}
            to={item.to}
            params={{ code }}
            aria-current={active === item.key ? "page" : undefined}
            className={cn(
              "flex min-h-12 flex-col items-center justify-center gap-1 rounded-xl px-1 py-1.5 text-[11px] transition-colors",
              active === item.key
                ? "bg-secondary font-semibold text-primary"
                : "text-muted-foreground hover:bg-secondary/50",
            )}
          >
            <item.icon className="size-5" />
            {item.label}
          </Link>
        ))}
      </nav>
    </div>
  )
}

export default StudentShell

function NotificationBell({ code }: { code: string }) {
  const student = loadStudent(code)
  const todayQuery = useQuery({
    queryKey: ["classroom", code, "today", student?.id],
    queryFn: () => ClassesService.readTodayPlan({ code: code.toUpperCase() }),
    enabled: student !== null && code !== "",
    retry: 1,
    retryDelay: 500,
    staleTime: 60_000,
  })
  const plan = todayQuery.data
  const g = plan?.gamification
  const done =
    plan?.attempts.filter((a) => a.status === "done" || a.status === "failed")
      .length ?? 0
  const total = plan?.items.length ?? 0
  const today = new Date().toLocaleDateString("en-CA")
  const newBadges = (g?.badges ?? []).filter(
    (b) =>
      b.awarded_at &&
      new Date(b.awarded_at).toLocaleDateString("en-CA") === today,
  )

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label="学习消息"
          className="relative size-9 text-muted-foreground sm:size-11"
        >
          <Bell className="size-[18px]" />
          {newBadges.length > 0 && (
            <span className="absolute right-2 top-2 size-2 rounded-full bg-accent-foreground ring-2 ring-card" />
          )}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>学习空间的消息</DialogTitle>
          <DialogDescription>
            今天的练习进度和属于你的小小进步。
          </DialogDescription>
        </DialogHeader>
        {todayQuery.isPending ? (
          <p role="status" className="py-5 text-sm text-muted-foreground">
            正在加载学习消息…
          </p>
        ) : todayQuery.isError ? (
          <div role="alert" className="space-y-3 text-sm">
            <p>消息暂未加载，请稍后重试。</p>
            <Button variant="outline" onClick={() => void todayQuery.refetch()}>
              重新加载
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="rounded-2xl bg-secondary/60 p-5">
              <p className="text-xs font-semibold text-primary">今日练习</p>
              <p className="mt-2 font-semibold">
                {total === 0
                  ? "等待老师安排今天的内容"
                  : done >= total
                    ? "今天的练习已完成，辛苦啦"
                    : `已完成 ${done}/${total} 题`}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                {total === 0
                  ? "也可以先到主题探索，自主练习。"
                  : done >= total
                    ? "到我的成长，看看今天的收获。"
                    : "不着急，按自己的节奏继续。"}
              </p>
            </div>
            {g && (g.streak_days ?? 0) > 0 && (
              <p className="rounded-2xl border p-4 text-sm">
                你已经坚持练习{" "}
                <strong className="text-primary">{g.streak_days}</strong>{" "}
                天，一步一步来，就很好。
              </p>
            )}
            {newBadges.length > 0 && (
              <p className="rounded-2xl bg-accent p-4 text-sm text-accent-foreground">
                获得新徽章 · {newBadges.map((b) => b.label).join("、")}
              </p>
            )}
            <DialogClose asChild>
              <Button asChild className="mt-2 w-full">
                <Link
                  to={
                    total === 0
                      ? "/explore/$code"
                      : done >= total
                        ? "/me/$code"
                        : "/p/$code"
                  }
                  params={{ code }}
                >
                  {total === 0
                    ? "去主题探索"
                    : done >= total
                      ? "查看我的成长"
                      : "继续今日练习"}
                  <ArrowRight />
                </Link>
              </Button>
            </DialogClose>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
