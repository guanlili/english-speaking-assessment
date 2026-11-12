import { createFileRoute, Link, redirect } from "@tanstack/react-router"
import {
  ArrowRight,
  AudioLines,
  BookOpenText,
  CalendarCheck,
  ClipboardCheck,
  GraduationCap,
  Mic,
  ShieldCheck,
  Sparkles,
  UsersRound,
} from "lucide-react"

import { SiteShell } from "@/components/Site/SiteShell"
import { Button } from "@/components/ui/button"
import { APP_NAME, SUPPORT_EMAIL } from "@/config"
import { cachedRole, isLoggedIn } from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

export const Route = createFileRoute("/")({
  component: LandingPage,
  beforeLoad: () => {
    // 已登录的人打开 `/` 不该看营销页：沿用原先的分流
    // （侧栏 Logo、404 的「返回首页」都指向 `/`，行为必须与改造前一致）
    if (!isLoggedIn()) return
    const role = cachedRole()
    if (role === "operator") throw redirect({ to: "/admin/dashboard" })
    if (role === "student") throw redirect({ to: "/join" })
    throw redirect({ to: "/classrooms" })
  },
  head: () => ({
    meta: [
      {
        title: `${APP_NAME} · 学校英语口语课堂 / Spoken English for Schools`,
      },
      {
        name: "description",
        content:
          "面向学校的英语口语课堂工具：文章朗读、听句复述、情景问答，老师发布即全班同步，作答保留录音、参考分与教师点评。",
      },
    ],
  }),
})

const EYEBROW =
  "mb-3 flex items-center gap-2.5 text-[11px] font-semibold tracking-[0.16em] text-muted-foreground"
const HAIRLINE = "h-px w-7 bg-tan-umber dark:bg-tan"
const CARD =
  "rounded-2xl border border-brand-ink/12 bg-paper-card p-5 shadow-[var(--shadow-brand-card)] dark:border-border dark:bg-card dark:shadow-none"

function LandingPage() {
  const { t } = useI18n()

  const entries = [
    {
      icon: GraduationCap,
      label: t({ zh: "教师与学校管理员", en: "Teachers & admins" }),
      action: t({
        zh: "用学校邮箱登录，创建班级、发布今日练习，课后回看作答、录音与点评。",
        en: "Sign in with your school email, create classes, publish today's practice, then review answers, recordings and feedback.",
      }),
      cta: t({ zh: "教师登录", en: "Teacher sign in" }),
      to: "/login" as const,
    },
    {
      icon: Mic,
      label: t({ zh: "学生", en: "Students" }),
      action: t({
        zh: "用学号登录后进入课堂；老师发的课堂链接打开即可上课，作业、参考分与成长都在这里。",
        en: "Sign in with your student ID and enter class. A class link from your teacher opens straight into the lesson, with homework, reference scores and progress in one place.",
      }),
      cta: t({ zh: "进入课堂", en: "Enter class" }),
      to: "/join" as const,
    },
    {
      icon: ShieldCheck,
      label: t({ zh: "学校专属入口", en: "School entry" }),
      action: t({
        zh: "每所学校有自己的登录地址，网页上会显示学校名称；找不到时用通用入口按邮箱登录即可。",
        en: "Each school has its own sign-in address that shows the school name. If you can't find it, the general sign-in with your email works too.",
      }),
      cta: t({ zh: "怎么找到入口", en: "How to find it" }),
      to: "/help" as const,
    },
  ]

  const features = [
    {
      icon: BookOpenText,
      title: t({
        zh: "四类题型，贴合课堂",
        en: "Four task types, class-ready",
      }),
      body: t({
        zh: "文章朗读、听句复述、情景问答与题目说明，按单元组织；选中内容发布，全班看到的是同一份题。",
        en: "Read aloud, listen & repeat, scenario Q&A and instruction pages, organized by unit. What you publish is the same set of tasks for the whole class.",
      }),
    },
    {
      icon: AudioLines,
      title: t({ zh: "录音留得住", en: "Recordings stay reviewable" }),
      body: t({
        zh: "每次作答都保存原始录音，教师可逐题回放、标注重点，学生也能回听自己当时怎么说。",
        en: "Every attempt keeps its original recording. Teachers replay it item by item and flag what matters; students can hear exactly how they spoke.",
      }),
    },
    {
      icon: ClipboardCheck,
      title: t({ zh: "分数说清来源", en: "Scores with clear sources" }),
      body: t({
        zh: "跟读引擎分、模型建议分与词表口径分开标注，界面写明这是练习参考分，不作为官方成绩。",
        en: "Engine scores, model suggestions and word-list levels are labelled separately, and the UI states clearly that these are practice references, not official results.",
      }),
    },
    {
      icon: CalendarCheck,
      title: t({ zh: "课堂同步不落后", en: "In step with the class" }),
      body: t({
        zh: "老师发布后学生端即时看到今日练习；已发布的练习按当时的题目快照解释，后续改题库不影响历史。",
        en: "Students see today's practice the moment you publish. Published work is read from a snapshot, so later question-bank edits never rewrite history.",
      }),
    },
    {
      icon: UsersRound,
      title: t({
        zh: "点评、补练与跟进",
        en: "Feedback, follow-ups, follow-through",
      }),
      body: t({
        zh: "逐题点评与指定补练，跟进结果单独记录；班级进度与个体作答在教师面板一处看完。",
        en: "Item-level feedback, targeted follow-up practice and recorded outcomes — class progress and individual answers in one teacher workspace.",
      }),
    },
    {
      icon: Sparkles,
      title: t({
        zh: "词汇、模考与学情",
        en: "Vocabulary, mock exams, evidence",
      }),
      body: t({
        zh: "五级词书、看义拼写与错词本，模考逐题限时；学情报告 PDF 与口语原音频 ZIP 可导出。",
        en: "Five-level word books, meaning-and-spelling practice and a wrong-word book; timed mock exams, with student reports as PDF and original audio as ZIP.",
      }),
    },
  ]

  const steps = [
    {
      number: "01",
      title: t({ zh: "开通学校空间", en: "Open the school space" }),
      body: t({
        zh: "联系平台运营方开通学校租户，拿到学校专属登录链接与管理员账号。",
        en: "Ask the platform team to open a school tenant; you get a school-specific sign-in link and an administrator account.",
      }),
    },
    {
      number: "02",
      title: t({
        zh: "导入师生，建班选内容",
        en: "Import people, build classes",
      }),
      body: t({
        zh: "批量导入教师与学生账号，建好班级，按单元挑选篇目、句型与情景题。",
        en: "Import teacher and student accounts in bulk, create classes, then pick passages, sentence frames and scenarios by unit.",
      }),
    },
    {
      number: "03",
      title: t({ zh: "发布第一堂课", en: "Publish the first lesson" }),
      body: t({
        zh: "课上发布今日练习，全班同时开口；课后看录音、参考分与点评，安排补练。",
        en: "Publish today's practice in class, everyone speaks at once, then review recordings, reference scores and feedback to plan follow-ups.",
      }),
    },
  ]

  return (
    <SiteShell>
      <section className="mx-auto grid max-w-[1440px] items-center gap-8 px-5 pb-12 pt-8 sm:px-10 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:gap-16 lg:px-16 lg:pb-20 lg:pt-14">
        <div className="page-enter mx-auto w-full max-w-[560px] lg:mx-0">
          <p className={EYEBROW}>
            <span className={HAIRLINE} aria-hidden="true" />
            {t({
              zh: "为学校英语口语课堂而做",
              en: "BUILT FOR THE SPOKEN ENGLISH CLASSROOM",
            })}
          </p>
          <h1 className="text-[30px] font-semibold leading-[1.2] tracking-tight sm:text-4xl lg:text-[42px]">
            {t({
              zh: "让每个学生，都敢开口。",
              en: "Every student, a confident voice.",
            })}
          </h1>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            {t({
              zh: "老师在前面授课，全班在电脑或 iPad 上同步开口说。每次作答都有录音、参考分和教师点评，课后可以逐题回看。",
              en: "Teachers lead the lesson while the whole class speaks on laptops or iPads at the same time. Every answer keeps its recording, reference score and teacher feedback, so you can revisit it item by item.",
            })}
          </p>

          <div className="mt-7 flex flex-col gap-3 sm:flex-row">
            <Button asChild size="lg">
              <Link to="/login">
                {t({ zh: "教师登录", en: "Teacher sign in" })}
                <ArrowRight aria-hidden="true" />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link to="/join">
                {t({ zh: "学生进入课堂", en: "Enter class" })}
              </Link>
            </Button>
          </div>
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            {t({
              zh: "第一次来？先看 ",
              en: "New here? Start with ",
            })}
            <Link
              to="/help"
              className="font-medium text-tan-sepia underline-offset-4 hover:underline dark:text-tan"
            >
              {t({ zh: "使用帮助", en: "the help guide" })}
            </Link>
            {t({ zh: " 或 ", en: " or " })}
            <Link
              to="/about"
              className="font-medium text-tan-sepia underline-offset-4 hover:underline dark:text-tan"
            >
              {t({ zh: "平台介绍", en: "what the platform is" })}
            </Link>
            {t({ zh: "。", en: "." })}
          </p>
        </div>

        <div className="learning-hero page-enter relative mx-auto w-full max-w-[560px] overflow-hidden rounded-2xl p-6 sm:p-7 lg:mx-0 lg:max-w-none xl:p-9">
          <div
            className="pointer-events-none absolute -right-20 top-10 size-72 rounded-full border border-tan-linen/15 before:absolute before:inset-7 before:rounded-full before:border before:border-tan-linen/15 after:absolute after:inset-14 after:rounded-full after:border after:border-tan-linen/15"
            aria-hidden="true"
          />
          <p
            className="relative flex items-center gap-2 text-[10px] font-medium tracking-[0.2em] text-mint-soft"
            lang="en"
          >
            <AudioLines className="size-4" aria-hidden="true" />
            LISTEN. SPEAK. GROW.
          </p>
          <p className="relative mt-4 text-sm text-paper-ivory/80">
            {t({
              zh: "今日练习 · 全班同步",
              en: "Today's practice · whole class",
            })}
          </p>

          <ul className="relative mt-4 space-y-2.5">
            {[
              {
                title: t({ zh: "文章朗读", en: "Read aloud" }),
                meta: t({
                  zh: "Pets and People · 1 篇",
                  en: "Pets and People · 1 passage",
                }),
              },
              {
                title: t({ zh: "听句复述", en: "Listen & repeat" }),
                meta: t({
                  zh: "3 句 · 参考分",
                  en: "3 sentences · reference score",
                }),
              },
              {
                title: t({ zh: "情景问答", en: "Scenario Q&A" }),
                meta: t({
                  zh: "宠物主题 · 2 题",
                  en: "Pets topic · 2 questions",
                }),
              },
            ].map((item) => (
              <li
                key={item.title}
                className="flex items-center justify-between gap-3 rounded-xl border border-white/15 bg-white/5 px-3.5 py-3"
              >
                <span className="text-sm font-medium text-paper-ivory">
                  {item.title}
                </span>
                <span className="shrink-0 text-xs text-mint-mist">
                  {item.meta}
                </span>
              </li>
            ))}
          </ul>

          <div
            className="relative mt-5 flex items-center gap-4 border-t border-white/20 pt-4"
            aria-hidden="true"
          >
            <span className="grid size-10 shrink-0 place-items-center rounded-full border border-tan/50 text-tan">
              <Mic className="size-4" />
            </span>
            <div className="flex h-10 min-w-0 flex-1 items-center justify-between gap-1">
              {Array.from({ length: 31 }, (_, index) => (
                <span
                  key={`hero-wave-${index}`}
                  className={`w-1 rounded-full ${index > 10 && index < 20 ? "bg-tan" : "bg-mint-mist/65"} ${["h-2", "h-4", "h-6", "h-3", "h-8", "h-10", "h-5"][index % 7]}`}
                />
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-[1440px] border-t border-brand-ink/10 px-5 py-12 sm:px-10 lg:px-16 lg:py-16 dark:border-border">
        <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          {t({ zh: "三个入口，各自直达", en: "Three doors, one platform" })}
        </h2>
        <p className="mt-3 max-w-[46rem] text-sm leading-6 text-muted-foreground">
          {t({
            zh: "老师、学生与学校管理员走的是不同入口，不要互相转发链接——尤其别把教师登录链接发给学生。",
            en: "Teachers, students and school admins each use a different door. Don't forward one link as another — especially not the teacher sign-in link to students.",
          })}
        </p>

        <div className="mt-7 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {entries.map((entry) => (
            <article key={entry.label} className={CARD}>
              <span className="grid size-11 place-items-center rounded-xl bg-primary/10 text-primary dark:bg-primary/15">
                <entry.icon className="size-5" aria-hidden="true" />
              </span>
              <h3 className="mt-4 text-base font-semibold">{entry.label}</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {entry.action}
              </p>
              <Link
                to={entry.to}
                className="mt-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-primary underline-offset-4 hover:underline"
              >
                {entry.cta}
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </article>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-[1440px] border-t border-brand-ink/10 px-5 py-12 sm:px-10 lg:px-16 lg:py-16 dark:border-border">
        <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          {t({
            zh: "课堂里真正用得上的六件事",
            en: "Six things that matter in class",
          })}
        </h2>
        <div className="mt-7 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((feature) => (
            <article key={feature.title} className={`${CARD} h-full`}>
              <feature.icon
                className="size-5 text-tan-umber dark:text-tan"
                aria-hidden="true"
              />
              <h3 className="mt-3 text-base font-semibold">{feature.title}</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {feature.body}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-[1440px] border-t border-brand-ink/10 px-5 py-12 sm:px-10 lg:px-16 lg:py-16 dark:border-border">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] lg:gap-16">
          <div>
            <p className={EYEBROW}>
              <span className={HAIRLINE} aria-hidden="true" />
              {t({ zh: "给学校的开通路径", en: "ONBOARDING FOR SCHOOLS" })}
            </p>
            <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              {t({
                zh: "把第一堂课开起来，只要三步",
                en: "Three steps to your first lesson",
              })}
            </h2>
            <div className="mt-6 rounded-2xl border border-brand-ink/12 bg-paper-warm/60 p-5 dark:border-border dark:bg-secondary/20">
              <h3 className="text-sm font-semibold">
                {t({ zh: "联系我们", en: "Talk to us" })}
              </h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {t({
                  zh: "学校开通、批量建号与培训请联系平台运营方或你所在学校的平台管理员；账号与数据归属学校，删除请求也走校方渠道。",
                  en: "For onboarding, bulk accounts and training, contact the platform team or your school's platform administrator. Accounts and data belong to the school, so deletion requests go through the school too.",
                })}
              </p>
              {SUPPORT_EMAIL !== "" ? (
                <a
                  href={`mailto:${SUPPORT_EMAIL}`}
                  className="mt-3 inline-flex min-h-11 items-center text-sm font-medium text-tan-sepia underline-offset-4 hover:underline dark:text-tan"
                >
                  {SUPPORT_EMAIL}
                </a>
              ) : (
                <Link
                  to="/help"
                  className="mt-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-primary underline-offset-4 hover:underline"
                >
                  {t({
                    zh: "查看联系方式与常见问题",
                    en: "See contact and FAQ",
                  })}
                  <ArrowRight className="size-4" aria-hidden="true" />
                </Link>
              )}
            </div>
          </div>

          <ol className="space-y-3">
            {steps.map((step) => (
              <li key={step.number} className={`${CARD} flex gap-4`}>
                <span
                  className="font-['Iowan_Old_Style','Palatino_Linotype',Georgia,serif] text-2xl italic text-tan-sepia dark:text-tan"
                  aria-hidden="true"
                >
                  {step.number}
                </span>
                <div className="min-w-0">
                  <h3 className="text-base font-semibold">{step.title}</h3>
                  <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
                    {step.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </SiteShell>
  )
}
