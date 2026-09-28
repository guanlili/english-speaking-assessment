import { createFileRoute, Link } from "@tanstack/react-router"
import { BookOpenText, Ear, MessagesSquare, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { APP_NAME } from "@/config"

export const Route = createFileRoute("/create")({
  component: CreateHubPage,
  head: () => ({ meta: [{ title: `出题中心 - ${APP_NAME}` }] }),
})

const TYPES = [
  {
    icon: BookOpenText,
    title: "朗读跟读题",
    subtitle: "读一段文章，录下来，AI 批改",
    what: "老师准备一篇英语短文（可配标准音），学生整篇朗读一遍，系统从完整度/流利度/准确度批改。",
    how: "在「篇目与朗读题」里新建篇目：贴入文章、选单元和难度、配标准音（可用 AI 生成或上传）。",
    to: "/admin/passages",
    action: "去篇目管理",
  },
  {
    icon: Ear,
    title: "听句复述题",
    subtitle: "听一句英语（限次数），复述出来",
    what: "学生听标准音（可限制重听次数，如 3 次），凭记忆复述整句，系统逐句比对打分。",
    how: "在「篇目与朗读题」里打开篇目，添加复述句（每句可设重听次数；也可用「自动拆分」从文章切句）。",
    to: "/admin/passages",
    action: "去添加复述句",
  },
  {
    icon: MessagesSquare,
    title: "口语问答题",
    subtitle: "模拟口语考试的一问一答",
    what: "按主题和难度（A2/B1/B2）出问答题，学生听题后自由作答，AI 从内容和流利度给反馈。",
    how: "在「问答题库」里批量粘贴（每行：英文题目 | 中文提示 | 建议秒数），或用 AI 起草后修改。",
    to: "/admin/questions",
    action: "去问答题库",
  },
]

/** 出题中心：三种题型的统一入口（教师/管理员）。 */
function CreateHubPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">出题中心</h1>
        <p className="text-muted-foreground">
          三种题型覆盖口语训练全场景；出的题进入全校共享题库，按单元组织后指派给课堂。
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        {TYPES.map((t) => (
          <Card key={t.title} className="flex flex-col">
            <CardHeader>
              <div className="mb-2 grid size-10 place-items-center rounded-lg bg-secondary">
                <t.icon className="size-5 text-primary" />
              </div>
              <CardTitle className="text-lg">{t.title}</CardTitle>
              <CardDescription>{t.subtitle}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-1 flex-col gap-3">
              <div className="text-sm leading-6">
                <p className="mb-1 text-xs font-semibold text-muted-foreground">
                  学生看到什么
                </p>
                {t.what}
              </div>
              <div className="text-sm leading-6">
                <p className="mb-1 text-xs font-semibold text-muted-foreground">
                  怎么出题
                </p>
                {t.how}
              </div>
              <Button asChild className="mt-auto w-full">
                <Link to={t.to}>
                  <Plus className="size-4" />
                  {t.action}
                </Link>
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">出完题之后</CardTitle>
          <CardDescription>
            到「我的课堂」打开教师面板 →
            指派单元（可勾选本轮题型，如纯问答专项）→ 学生打开就是本轮内容
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild variant="outline" size="sm">
            <Link to="/classrooms">去我的课堂</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
