import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router"
import { ArrowRight, ChartLine, Headphones, MessageCircle } from "lucide-react"
import { useEffect, useState } from "react"
import { ClassesService, UsersService } from "@/client"
import { Logo } from "@/components/Common/Logo"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { LoadingButton } from "@/components/ui/loading-button"
import { APP_NAME } from "@/config"
import { isStudentLoggedIn } from "@/hooks/useAuth"
import { loadStudent, saveStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"

export const Route = createFileRoute("/j/$code")({
  component: JoinPage,
  head: () => ({
    meta: [{ title: `进入课堂 / Join a Class - ${APP_NAME}` }],
  }),
})

function JoinPage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/j/$code" })
  const navigate = useNavigate({ from: "/j/$code" })
  const [error, setError] = useState<string | null>(null)
  const meQuery = useQuery({
    queryKey: ["join-me"],
    queryFn: () => UsersService.readUserMe(),
    enabled: isStudentLoggedIn(),
  })

  // 未登录学生 → 登录页（学生 Tab）；已在本课堂 → 直接进练习页
  useEffect(() => {
    if (!isStudentLoggedIn()) {
      void navigate({ to: "/login" })
      return
    }
    if (loadStudent(code)) {
      void navigate({ to: "/home/$code", params: { code } })
    }
  }, [code, navigate])

  const joinMutation = useMutation({
    mutationFn: () =>
      ClassesService.joinClass({
        code: code.toUpperCase(),
        requestBody: {},
      }),
    onSuccess: (student) => {
      saveStudent(code, student)
      void navigate({ to: "/home/$code", params: { code } })
    },
    onError: () => {
      setError(
        t({
          zh: "进入失败：课堂码可能不对，请和老师核对",
          en: "Couldn't join: the classroom code may be incorrect — please check with your teacher",
        }),
      )
    },
  })

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-7">
        <Logo asLink={false} />
        <span className="hidden text-xs text-muted-foreground sm:block">
          {t({
            zh: "每一次开口，都是向前一步",
            en: "Every time you speak, you move one step forward",
          })}
        </span>
      </header>
      <main className="mx-auto grid w-full max-w-6xl flex-1 items-center gap-7 px-6 py-4 lg:py-10 lg:grid-cols-[1.2fr_1fr] lg:gap-20">
        <section>
          <span className="inline-flex rounded-full border border-primary/15 bg-secondary px-3 py-1.5 text-xs font-semibold text-primary">
            {t({
              zh: "SpeakUp · 你的口语课堂",
              en: "SpeakUp · Your speaking class",
            })}
          </span>
          <h1 className="mt-4 text-3xl lg:mt-6 font-bold leading-tight tracking-tight md:text-5xl">
            {t({ zh: "从今天开始，", en: "Starting today," })}
            <br />
            <span className="text-primary">
              {t({ zh: "自在开口表达。", en: "speak up with ease." })}
            </span>
          </h1>
          <p className="mt-4 max-w-md text-sm leading-7 text-muted-foreground">
            {t({
              zh: "跟随老师的节奏，听一听、说一说。",
              en: "Follow your teacher's pace — listen a little, speak a little.",
            })}
            <br />
            {t({
              zh: "不必追求完美，每一次表达都值得鼓励。",
              en: "It doesn't have to be perfect — every attempt deserves encouragement.",
            })}
          </p>
          <div className="mt-5 grid max-w-lg lg:mt-9 grid-cols-3 gap-4">
            {[
              {
                icon: Headphones,
                title: t(TERMS.typeRepeat),
                text: t({
                  zh: "积累自然表达",
                  en: "Build natural expressions",
                }),
              },
              {
                icon: MessageCircle,
                title: t(TERMS.typeQa),
                text: t({ zh: "分享你的想法", en: "Share your thoughts" }),
              },
              {
                icon: ChartLine,
                title: t({ zh: "看见成长", en: "See your growth" }),
                text: t({ zh: "记录每次进步", en: "Every step recorded" }),
              },
            ].map((item) => (
              <div key={item.title}>
                <item.icon className="mb-3 size-5 text-primary" />
                <p className="text-sm font-semibold">{item.title}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.text}
                </p>
              </div>
            ))}
          </div>
        </section>
        <Card className="w-full border-border/80 py-8 shadow-xl shadow-primary/5 sm:p-3">
          <CardHeader>
            <span className="mb-2 text-xs font-semibold tracking-widest text-primary">
              JOIN YOUR CLASS
            </span>
            <CardTitle className="text-2xl">
              {t({ zh: "进入你的课堂", en: "Join your class" })}
            </CardTitle>
            <CardDescription>
              {t({ zh: "课堂码", en: "Classroom Code" })}{" "}
              <span className="font-mono font-semibold">
                {code.toUpperCase()}
              </span>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                joinMutation.mutate()
              }}
              className="space-y-6"
            >
              <div className="rounded-xl bg-background/60 px-4 py-3 text-sm">
                <span className="text-muted-foreground">
                  {t({ zh: "将以账号姓名进入：", en: "Joining as:" })}
                </span>
                <span className="font-semibold">
                  {meQuery.data?.full_name ||
                    meQuery.data?.username ||
                    t({ zh: "同学", en: "Student" })}
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {t({
                    zh: "课堂内显示名使用学号账号的姓名，如需修改请联系老师。",
                    en: "Your display name in class is the name on your student ID account — contact your teacher to change it.",
                  })}
                </span>
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <LoadingButton
                type="submit"
                className="h-12 w-full"
                loading={joinMutation.isPending}
              >
                {t({ zh: "进入课堂", en: "Join class" })}{" "}
                <ArrowRight className="size-4" />
              </LoadingButton>
            </form>
            <p className="mt-5 text-center text-xs leading-6 text-muted-foreground">
              {t({
                zh: "用你的学号账号进入 · 老师能看见你的练习进度",
                en: "Join with your student ID account · Your teacher can see your practice progress",
              })}
            </p>
          </CardContent>
        </Card>
      </main>
      <footer className="px-6 py-6 text-center text-xs text-muted-foreground">
        {t({
          zh: "SpeakUp 开口说 · 参考反馈仅用于学习，不代表官方考试成绩",
          en: "SpeakUp · Reference feedback is for learning only, not official exam results",
        })}
      </footer>
    </div>
  )
}
