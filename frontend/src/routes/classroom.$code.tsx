import { useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router"
import {
  ArrowRight,
  CheckCircle2,
  Copy,
  Headphones,
  LogOut,
} from "lucide-react"
import { useState } from "react"
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
import { useStudentGuard } from "@/hooks/useStudentGuard"
import { clearStudent, displayName, loadStudent } from "@/lib/classroom-student"
import { copyText } from "@/lib/clipboard"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"

export const Route = createFileRoute("/classroom/$code")({
  component: ClassroomPage,
  head: () => ({
    meta: [{ title: `我的课堂 / My Classroom - ${APP_NAME}` }],
  }),
})

function ClassroomPage() {
  const { t } = useI18n()
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
      }),
    enabled: student !== null,
    staleTime: 60_000,
  })

  useStudentGuard(code, student, todayQuery)

  const copyCode = async () => {
    if (await copyText(code.toUpperCase())) {
      toast.success(
        t({
          zh: `课堂码 ${code.toUpperCase()} 已复制`,
          en: `Classroom code ${code.toUpperCase()} copied`,
        }),
      )
    } else {
      toast.error(
        t({
          zh: "复制失败，请手动记录课堂码",
          en: "Copy failed — please write down the classroom code",
        }),
      )
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
            {t({
              zh: "不是一个人练习，是一起成长。",
              en: "You're not practicing alone — you're growing together.",
            })}
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            {t({
              zh: "你的课堂信息与身份管理。",
              en: "Your classroom info and identity management.",
            })}
          </p>
        </div>

        <Card className="bg-secondary/60">
          <CardHeader>
            <CardDescription>MY CLASSROOM</CardDescription>
            <CardTitle className="text-lg">
              {student
                ? t({
                    zh: `你好，${displayName(student)}`,
                    en: `Hi, ${displayName(student)}`,
                  })
                : t({ zh: "还未加入", en: "Not joined yet" })}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-xs text-muted-foreground">
                {t({ zh: "课堂码", en: "Classroom Code" })}
              </p>
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
                {t({ zh: "复制课堂码", en: "Copy code" })}
              </Button>
              <span className="text-xs text-muted-foreground">
                {t({
                  zh: "课堂码只和本班同学分享",
                  en: "Share the classroom code only with your classmates",
                })}
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t(TERMS.todayPractice)}
            </CardTitle>
            <CardDescription>
              {todayQuery.data?.assigned_unit_title
                ? t({
                    zh: `老师指派：${todayQuery.data.assigned_unit_title}`,
                    en: `Assigned by your teacher: ${todayQuery.data.assigned_unit_title}`,
                  })
                : t({
                    zh: "老师未指派时，按你自己的关卡进度练习",
                    en: "When your teacher hasn't assigned one, practice follows your own level progress",
                  })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-secondary text-primary">
                <Headphones className="size-5" />
              </span>
              <div className="flex-1">
                <p className="text-sm font-semibold">
                  {todayQuery.data?.assigned_unit_title ??
                    t(TERMS.selfPractice)}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t({
                    zh: "3 句听句复述 + 2 道情景问答 · 约 10 分钟",
                    en: "3 Listen & Repeat + 2 Scenario Q&A · about 10 min",
                  })}
                </p>
              </div>
            </div>
            <Button
              onClick={() =>
                void navigate({ to: "/p/$code", params: { code } })
              }
            >
              {t({ zh: "开始课堂练习", en: "Start classroom practice" })}{" "}
              <ArrowRight />
            </Button>
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "没有公开排名，老师看到的是你的练习进度与参考反馈。",
                en: "No public rankings — your teacher sees your practice progress and reference feedback.",
              })}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t({ zh: "退出课堂", en: "Leave classroom" })}
            </CardTitle>
            <CardDescription>
              {t({
                zh: "换设备或想以其他身份开始时，先退出当前课堂。练习记录保存在你的学生账号下，重新登录同一账号并进入课堂即可找回。",
                en: "Leaving for another device, or starting as someone else? Leave this classroom first. Your practice records live in your student account — sign in again with the same account and rejoin to get them back.",
              })}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!confirmExit ? (
              <Button variant="outline" onClick={() => setConfirmExit(true)}>
                <LogOut />
                {t({ zh: "退出课堂", en: "Leave classroom" })}
              </Button>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-muted-foreground">
                  {t({
                    zh: "确定退出当前课堂？",
                    en: "Leave this classroom?",
                  })}
                </span>
                <Button variant="destructive" size="sm" onClick={leave}>
                  {t({ zh: "确定退出", en: "Yes, leave" })}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirmExit(false)}
                >
                  {t({ zh: "先不退出", en: "Stay" })}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t({
                zh: "放心开口的小约定",
                en: "Our little agreement for safe speaking",
              })}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5 text-sm">
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              {t({
                zh: "用学生账号登录进入课堂，练习记录跟随账号保存；课堂里用显示名与区分码区分同学。",
                en: "Sign in with your student account to join class — practice records follow the account; classmates are told apart by display names and distinct codes.",
              })}
            </p>
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              {t({
                zh: "成绩仅供学习参考；老师关注的是你的变化，不是一次分数。",
                en: "Scores are for learning only; your teacher cares about your progress, not a single score.",
              })}
            </p>
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              {t({
                zh: "音频只用于学习反馈，只有你自己和本课授权老师可回听，不做其他用途。",
                en: "Audio is used only for learning feedback; only you and your classroom's authorized teacher can play it back.",
              })}
            </p>
          </CardContent>
        </Card>
      </div>
    </StudentShell>
  )
}
