import { useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router"
import {
  ArrowRight,
  CheckCircle2,
  Copy,
  Headphones,
  LogOut,
} from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { ClassesService } from "@/client"
import StudentShell from "@/components/Practice/StudentShell"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { APP_NAME } from "@/config"
import {
  clearStudent,
  displayName,
  isStudentNotFound,
  loadStudent,
} from "@/lib/classroom-student"

export const Route = createFileRoute("/classroom/$code")({
  component: ClassroomPage,
  head: () => ({ meta: [{ title: `我的课堂 - ${APP_NAME}` }] }),
})

function ClassroomPage() {
  const { code } = useParams({ from: "/classroom/$code" })
  const navigate = useNavigate({ from: "/classroom/$code" })
  const student = loadStudent(code)
  const [confirmExit, setConfirmExit] = useState(false)

  const todayQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["classroom", code, "today", student?.id],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    enabled: student !== null,
    staleTime: 60_000,
  })

  useEffect(() => {
    if (todayQuery.isError && isStudentNotFound(todayQuery.error)) {
      clearStudent(code)
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [todayQuery.isError, todayQuery.error, code, navigate])

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(code.toUpperCase())
      toast.success(`课堂码 ${code.toUpperCase()} 已复制`)
    } catch {
      toast.error("复制失败，请手动记录课堂码")
    }
  }

  const leave = () => {
    clearStudent(code)
    void navigate({ to: "/j/$code", params: { code } })
  }

  return (
    <StudentShell active="classroom">
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            不是一个人练习，是一起成长。
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            你的课堂信息与身份管理。
          </p>
        </div>

        <Card className="bg-secondary/60">
          <CardHeader>
            <CardDescription>MY CLASSROOM</CardDescription>
            <CardTitle className="text-lg">
              {student ? `你好，${displayName(student)}` : "还未加入"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-xs text-muted-foreground">课堂码</p>
              <p className="font-mono text-4xl font-bold tracking-[0.3em]">
                {code.toUpperCase()}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void copyCode()}
              >
                <Copy />
                复制课堂码
              </Button>
              <span className="text-xs text-muted-foreground">
                课堂码只和本班同学分享
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">今日课堂任务</CardTitle>
            <CardDescription>
              {todayQuery.data?.assigned_unit_title
                ? `老师指派：${todayQuery.data.assigned_unit_title}`
                : "老师未指派时，按你自己的关卡进度练习"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-secondary text-primary">
                <Headphones className="size-5" />
              </span>
              <div className="flex-1">
                <p className="text-sm font-semibold">
                  {todayQuery.data?.assigned_unit_title ?? "个人关卡"}
                </p>
                <p className="text-xs text-muted-foreground">
                  3 句听后复述 + 2 道情景问答 · 约 10 分钟
                </p>
              </div>
            </div>
            <Button
              onClick={() =>
                void navigate({ to: "/p/$code", params: { code } })
              }
            >
              开始课堂练习 <ArrowRight />
            </Button>
            <p className="text-xs text-muted-foreground">
              没有公开排名，老师看到的是你的练习进度与参考反馈。
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">换一个名字 / 退出课堂</CardTitle>
            <CardDescription>
              换设备练习、名字打错了，或想以新身份开始时使用。练习记录保存在服务器，
              重新输入同一个名字不会找回旧记录（同名会分配新的区分码）。
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!confirmExit ? (
              <Button variant="outline" onClick={() => setConfirmExit(true)}>
                <LogOut />
                退出并重新进入
              </Button>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-muted-foreground">
                  确定退出当前身份？
                </span>
                <Button variant="destructive" size="sm" onClick={leave}>
                  确定，重新进入
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirmExit(false)}
                >
                  先不退出
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">放心开口的小约定</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5 text-sm">
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              显示名 + 区分码识别身份，不需要注册账号。
            </p>
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              成绩仅供学习参考；老师关注的是你的变化，不是一次分数。
            </p>
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              音频只用于学习反馈，老师可回听，不做其他用途。
            </p>
          </CardContent>
        </Card>
      </div>
    </StudentShell>
  )
}
