import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowRight,
  BookOpen,
  GraduationCap,
  Layers,
  ListChecks,
  PenLine,
  School,
  UsersRound,
} from "lucide-react"
import { APP_NAME } from "@/config"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({ meta: [{ title: `教学工作台 - ${APP_NAME}` }] }),
})

const modules = [
  {
    to: "/admin/classrooms",
    icon: UsersRound,
    title: "课堂管理",
    description: "创建课堂码，邀请学生加入课堂。",
    step: "01",
  },
  {
    to: "/admin/units",
    icon: Layers,
    title: "学习单元",
    description: "编排关卡单元，把篇目挂到单元上。",
    step: "02",
  },
  {
    to: "/admin/passages",
    icon: BookOpen,
    title: "篇目与复述",
    description: "准备阅读材料、复述短句和标准音。",
    step: "03",
  },
  {
    to: "/admin/scenarios",
    icon: ListChecks,
    title: "情景与问法",
    description: "编排分级问答，让表达贴近真实生活。",
    step: "04",
  },
  {
    to: "/admin/wordlist",
    icon: GraduationCap,
    title: "分级词表",
    description: "维护词汇分级，为学习反馈提供参考。",
    step: "05",
  },
] as const

// 教师端核心双入口：课堂 + 出题（其余内容管理从出题中心进）
const teacherModules = [
  {
    to: "/classrooms",
    icon: School,
    title: "我的课堂",
    description: "创建课堂、导入学生学号、指派今日练习、看全班进度。",
    step: "01",
  },
  {
    to: "/create",
    icon: PenLine,
    title: "出题中心",
    description: "三种题型：朗读跟读、听句复述（限重听）、口语问答。",
    step: "02",
  },
] as const

function Dashboard() {
  const { user } = useAuth()
  const isTeacher = !user?.is_superuser && user?.role !== "student"
  return (
    <div className="space-y-8">
      <div>
        <p className="mb-2 text-xs font-semibold tracking-widest text-primary">
          TEACHING WORKSPACE
        </p>
        <h1 className="text-3xl font-bold">
          你好，{user?.full_name || "老师"}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          让课堂准备更有序，让学生开口更自然。
        </p>
      </div>
      <section className="relative overflow-hidden rounded-3xl bg-primary p-7 text-primary-foreground md:p-10">
        <div className="max-w-xl">
          <span className="rounded-full border border-white/25 px-3 py-1 text-xs">
            从这里开始一堂口语课
          </span>
          <h2 className="mt-6 text-2xl font-semibold md:text-3xl">
            准备好内容，把表达交给学生。
          </h2>
          <p className="mt-3 text-sm leading-7 opacity-80">
            {user?.is_superuser
              ? "创建课堂、准备篇目与情景，再在教师面板指派今日练习，查看全班作答进度。"
              : "两步开始：出好题，在课堂面板指派给学生。其余交给学生和 AI。"}
          </p>
          {user?.is_superuser ? (
            <Link
              to="/admin/classrooms"
              className="mt-6 inline-flex items-center gap-3 rounded-xl bg-card px-5 py-3 text-sm font-semibold text-primary"
            >
              管理我的课堂 <ArrowRight className="size-4" />
            </Link>
          ) : (
            <Link
              to="/classrooms"
              className="mt-6 inline-flex items-center gap-3 rounded-xl bg-card px-5 py-3 text-sm font-semibold text-primary"
            >
              进入我的课堂 <ArrowRight className="size-4" />
            </Link>
          )}
        </div>
      </section>
      {isTeacher && (
        <section>
          <h2 className="mb-4 text-lg font-semibold">开始上课</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {teacherModules.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className="group rounded-2xl border bg-card p-6 transition hover:border-primary/40 hover:shadow-md"
              >
                <div className="flex items-center justify-between">
                  <span className="grid size-11 place-items-center rounded-xl bg-secondary text-primary">
                    <item.icon className="size-5" />
                  </span>
                  <span className="text-xs font-medium text-muted-foreground">
                    {item.step}
                  </span>
                </div>
                <h3 className="mt-6 font-semibold">{item.title}</h3>
                <p className="mt-2 min-h-12 text-sm leading-6 text-muted-foreground">
                  {item.description}
                </p>
                <span className="mt-5 flex items-center gap-2 text-xs font-semibold text-primary">
                  进入{" "}
                  <ArrowRight className="size-3.5 transition group-hover:translate-x-1" />
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}
      {user?.is_superuser && (
        <section>
          <h2 className="mb-4 text-lg font-semibold">教学准备</h2>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {modules.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className="group rounded-2xl border bg-card p-6 transition hover:border-primary/40 hover:shadow-md"
              >
                <div className="flex items-center justify-between">
                  <span className="grid size-11 place-items-center rounded-xl bg-secondary text-primary">
                    <item.icon className="size-5" />
                  </span>
                  <span className="text-xs font-medium text-muted-foreground">
                    {item.step}
                  </span>
                </div>
                <h3 className="mt-6 font-semibold">{item.title}</h3>
                <p className="mt-2 min-h-12 text-sm leading-6 text-muted-foreground">
                  {item.description}
                </p>
                <span className="mt-5 flex items-center gap-2 text-xs font-semibold text-primary">
                  进入管理{" "}
                  <ArrowRight className="size-3.5 transition group-hover:translate-x-1" />
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}
      <div className="rounded-2xl border border-dashed p-5 text-sm leading-7 text-muted-foreground">
        <strong className="text-foreground">课堂小提示</strong>
        <p>
          学生用学号登录后凭课堂码进入课堂。建议课前提醒学生检查耳机与麦克风，课后结合参考反馈安排下一次练习。
        </p>
        <p className="mt-1 text-xs">
          平台评分与词汇档位仅供教学参考，不代表官方考试成绩。
        </p>
      </div>
    </div>
  )
}
