import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { ArrowRight, ArrowRightLeft, CalendarCheck, Flame } from "lucide-react"
import { useEffect, useState } from "react"
import {
  ClassesService,
  type StudentClassroomOut,
  StudentsService,
} from "@/client"
import { Logo } from "@/components/Common/Logo"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { APP_NAME } from "@/config"
import { isStudentLoggedIn } from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { saveStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/join")({
  component: MyClassesPage,
  head: () => ({
    meta: [{ title: `我的班级 / My Classes - ${APP_NAME}` }],
  }),
})

/** 学生登录后的落点：列出已加入的全部班级（多班归属），并可凭课堂码加入新班。
 *
 * 成长数据按班内档案各自独立，卡片展示各班的 XP/连胜；
 * 顶部一行给跨班合计（账号总览），口径说明见需求「学生多班归属」。
 */
function MyClassesPage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { showErrorToast } = useCustomToast()
  const [code, setCode] = useState("")

  useEffect(() => {
    if (!isStudentLoggedIn()) void navigate({ to: "/login" })
  }, [navigate])

  const classesQuery = useQuery({
    queryKey: ["my-classrooms"],
    queryFn: () => StudentsService.listMyEnrollments(),
    enabled: isStudentLoggedIn(),
  })
  const classes = classesQuery.data ?? []
  const totalXp = classes.reduce((sum, c) => sum + (c.xp ?? 0), 0)
  const bestStreak = classes.reduce(
    (m, c) => Math.max(m, c.streak_days ?? 0),
    0,
  )

  // 入班幂等：新设备/本地身份被清后也能一键直达，不在 /j/$code 二次确认
  const enterMutation = useMutation({
    mutationFn: (classCode: string) =>
      ClassesService.joinClass({ code: classCode, requestBody: {} }),
    onSuccess: (student, classCode) => {
      saveStudent(classCode, student)
      void navigate({ to: "/home/$code", params: { code: classCode } })
    },
    onError: (error) => showErrorToast(extractErrorMessage(error)),
  })

  const enterClass = (c: StudentClassroomOut) => {
    enterMutation.mutate(c.code)
  }

  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="mx-auto flex w-full max-w-4xl items-center justify-between px-6 py-7">
        <Logo asLink={false} />
        <span className="hidden text-xs text-muted-foreground sm:block">
          {t({
            zh: "每一次开口，都是向前一步",
            en: "Every time you speak, you move one step forward",
          })}
        </span>
      </header>
      <main className="mx-auto w-full max-w-4xl flex-1 px-5 pb-16 sm:px-6">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
          {t({ zh: "我的班级", en: "My Classes" })}
        </h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          {t({
            zh: "你在多个班级的任务各自独立，选一个进入；也可以用课堂码加入新班级。",
            en: "Tasks from each of your classes are kept separate. Pick one to continue, or join a new class with its code.",
          })}
        </p>

        {classes.length > 0 && (
          <p className="mt-4 inline-flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-border/70 bg-secondary/50 px-4 py-2.5 text-xs text-muted-foreground">
            <span>
              {t({ zh: "账号总览：", en: "Account total: " })}
              <strong className="text-foreground">{totalXp} XP</strong>
            </span>
            {bestStreak > 0 && (
              <span className="inline-flex items-center gap-1">
                <Flame className="size-3.5 text-primary" aria-hidden="true" />
                <strong className="text-foreground">{bestStreak}</strong>
                {t({ zh: " 天最长连胜", en: " day best streak" })}
              </span>
            )}
            <span>
              {t({
                zh: "各班成长分开记录",
                en: "Growth is tracked per class",
              })}
            </span>
          </p>
        )}

        {classesQuery.isPending ? (
          <div
            className="mt-6 grid gap-4 sm:grid-cols-2"
            role="status"
            aria-label={t({ zh: "正在加载班级", en: "Loading your classes" })}
          >
            {[0, 1].map((i) => (
              <div
                key={i}
                className="h-44 animate-pulse rounded-2xl border border-border/60 bg-muted/40"
              />
            ))}
          </div>
        ) : classesQuery.isError ? (
          <div
            role="alert"
            className="mt-6 rounded-2xl border border-destructive/30 bg-destructive/5 p-5 text-sm"
          >
            <p>
              {t({
                zh: "班级列表暂时加载失败，请重试。",
                en: "Couldn't load your classes — please retry.",
              })}
            </p>
            <LoadingButton
              variant="outline"
              className="mt-3 h-11"
              onClick={() => void classesQuery.refetch()}
            >
              {t({ zh: "重新加载", en: "Reload" })}
            </LoadingButton>
          </div>
        ) : classes.length === 0 ? (
          <Card className="mt-6 border-dashed py-8">
            <CardHeader>
              <CardTitle className="text-lg">
                {t({ zh: "还没有加入任何班级", en: "No classes yet" })}
              </CardTitle>
              <CardDescription>
                {t({
                  zh: "输入老师给你的课堂码，进入你的第一个班级。",
                  en: "Enter the classroom code from your teacher to join your first class.",
                })}
              </CardDescription>
            </CardHeader>
          </Card>
        ) : (
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {classes.map((c) => (
              <Card
                key={c.classroom_id}
                className="flex flex-col gap-4 py-6 shadow-sm"
              >
                <CardHeader className="space-y-1.5">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="text-lg leading-snug">
                      {c.name}
                    </CardTitle>
                    {c.has_published_task && (
                      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold text-accent-foreground">
                        <CalendarCheck
                          className="size-3.5"
                          aria-hidden="true"
                        />
                        {t({ zh: "有进行中的任务", en: "Task in progress" })}
                      </span>
                    )}
                  </div>
                  <CardDescription className="font-mono text-xs tracking-widest">
                    {c.code}
                    {c.grade ? ` · ${c.grade}` : ""}
                  </CardDescription>
                </CardHeader>
                <CardContent className="mt-auto flex items-center justify-between gap-3">
                  <p className="text-xs text-muted-foreground">
                    {t({ zh: "本班 ", en: "In this class: " })}
                    <strong className="text-foreground">{c.xp ?? 0} XP</strong>
                    {(c.streak_days ?? 0) > 0 && (
                      <>
                        {" · "}
                        <Flame
                          className="inline size-3.5 text-primary"
                          aria-hidden="true"
                        />
                        <strong className="text-foreground">
                          {c.streak_days}
                        </strong>
                        {t({ zh: " 天连胜", en: "-day streak" })}
                      </>
                    )}
                  </p>
                  <LoadingButton
                    className="h-11 shrink-0"
                    loading={
                      enterMutation.isPending &&
                      enterMutation.variables === c.code
                    }
                    onClick={() => enterClass(c)}
                  >
                    {t({ zh: "进入课堂", en: "Enter class" })}
                    <ArrowRight className="size-4" aria-hidden="true" />
                  </LoadingButton>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        <section aria-label={t({ zh: "加入新班级", en: "Join a new class" })}>
          <div className="my-7 flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            <span className="inline-flex items-center gap-1.5">
              <ArrowRightLeft className="size-3.5" aria-hidden="true" />
              {t({ zh: "或", en: "or" })}
            </span>
            <span className="h-px flex-1 bg-border" />
          </div>
          <Card className="w-full py-8 shadow-xl shadow-primary/5">
            <CardHeader>
              <CardTitle className="text-2xl">
                {t({ zh: "加入新班级", en: "Join a Class" })}
              </CardTitle>
              <CardDescription>
                {t({
                  zh: "输入老师给你的课堂码开始练习",
                  en: "Enter the classroom code from your teacher to start practicing",
                })}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  const c = code.trim().toUpperCase()
                  if (c) void navigate({ to: "/j/$code", params: { code: c } })
                }}
                className="space-y-5"
              >
                <Input
                  className="h-12 text-center font-mono text-lg tracking-widest"
                  placeholder={t({
                    zh: "课堂码，如 DEMO01",
                    en: "Classroom code, e.g. DEMO01",
                  })}
                  maxLength={16}
                  value={code}
                  onChange={(e) => setCode(e.target.value.toUpperCase())}
                  aria-label={t({ zh: "课堂码", en: "Classroom code" })}
                />
                <LoadingButton type="submit" className="h-12 w-full">
                  {t({ zh: "下一步", en: "Next" })}{" "}
                  <ArrowRight className="size-4" aria-hidden="true" />
                </LoadingButton>
              </form>
            </CardContent>
          </Card>
        </section>
      </main>
      <footer className="px-6 pb-6 text-center text-xs text-muted-foreground">
        {t({
          zh: "Charcoal 开口说 · 参考反馈仅用于学习，不代表官方考试成绩",
          en: "Charcoal · Reference feedback is for learning only, not official exam results",
        })}
      </footer>
    </div>
  )
}
