import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowRight, BookOpenText, ShieldCheck, UsersRound } from "lucide-react"

import { SiteShell } from "@/components/Site/SiteShell"
import { APP_NAME } from "@/config"
import { useI18n } from "@/lib/i18n"
import { publicPageHead } from "@/lib/site-meta"

export const Route = createFileRoute("/about")({
  component: AboutPage,
  head: () =>
    publicPageHead({
      path: "/about",
      title: `关于平台 / About - ${APP_NAME}`,
      description:
        "英语口语课堂工具：老师发布练习、全班同步开口，作答留录音、参考分与教师点评；每所学校数据独立。",
    }),
})

const CARD =
  "rounded-2xl border border-brand-ink/12 bg-paper-card p-5 dark:border-border dark:bg-card"
const EYEBROW =
  "mb-3 flex items-center gap-2.5 text-[11px] font-semibold tracking-[0.16em] text-muted-foreground"
const HAIRLINE = "h-px w-7 bg-tan-umber dark:bg-tan"

function AboutPage() {
  const { t } = useI18n()

  const lessonSteps = [
    {
      number: "01",
      title: t({ zh: "老师发布", en: "The teacher publishes" }),
      body: t({
        zh: "按单元选好篇目、句型与情景题，一键发布今日练习；没选的题不进这节课。",
        en: "Pick passages, sentence frames and scenarios by unit, then publish today's practice in one step. What you don't pick never enters this lesson.",
      }),
    },
    {
      number: "02",
      title: t({ zh: "全班开口", en: "The class speaks" }),
      body: t({
        zh: "学生进入课堂后按题目顺序作答，每题录一次音；断网重传不会重复计分。",
        en: "Students enter class and answer in order, recording once per item. A retried upload after a dropped connection is never scored twice.",
      }),
    },
    {
      number: "03",
      title: t({ zh: "回看与补练", en: "Review and follow up" }),
      body: t({
        zh: "课后逐题回放录音、看参考分、写点评，指定补练并记录跟进结果。",
        en: "After class, replay each recording, read the reference score, leave feedback, assign follow-up practice and record its outcome.",
      }),
    },
  ]

  const capabilities = [
    {
      icon: BookOpenText,
      title: t({ zh: "内容与题型", en: "Content and task types" }),
      body: t({
        zh: "篇目、单元、句型、情景题与自建练习组成学校自己的题库；文章朗读、听句复述、情景问答、题目说明四类题型共用一套发布流程。",
        en: "Passages, units, sentence frames, scenarios and self-built exercises form the school's own bank. Read aloud, listen & repeat, scenario Q&A and instructions share one publishing flow.",
      }),
    },
    {
      icon: UsersRound,
      title: t({ zh: "班级与教学闭环", en: "Classes and the teaching loop" }),
      body: t({
        zh: "建班、加入学生、布置作业、查看作答与诊断、讲评与补练，都在教师工作台里；班主任与任课教师看到的是同一份班级进度。",
        en: "Create classes, enroll students, assign work, review answers and diagnostics, then teach back and assign follow-ups — all in one teacher workspace.",
      }),
    },
    {
      icon: ShieldCheck,
      title: t({ zh: "每所学校各自独立", en: "Every school is separate" }),
      body: t({
        zh: "平台按学校（租户）隔离：每所学校的数据互相不可见、不可编辑；学校被停用时，该校所有会话立即失效。",
        en: "The platform isolates each school as its own tenant: data is invisible and immutable across schools, and disabling a school invalidates all of its sessions immediately.",
      }),
    },
  ]

  return (
    <SiteShell>
      <article className="mx-auto max-w-[1440px] px-5 pt-10 sm:px-10 lg:px-16 lg:pt-14">
        <header className="page-enter max-w-[62rem]">
          <p className={EYEBROW}>
            <span className={HAIRLINE} aria-hidden="true" />
            {t({ zh: "关于平台", en: "ABOUT" })}
          </p>
          <h1 className="text-[28px] font-semibold leading-tight tracking-tight sm:text-4xl">
            {t({
              zh: "这是一个课堂工具，不是又一个自学 App。",
              en: "This is a classroom tool, not another self-study app.",
            })}
          </h1>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            {t({
              zh: "课堂节奏由老师决定：老师选内容、发布练习、当场讲评。平台负责把练习发下去、把声音收上来，并把录音、参考分和点评留在能被回看的地方。学生在课后可以用自主练习和词书补，但那只是兜底，不是主线。",
              en: "The teacher sets the pace: choosing content, publishing practice and giving feedback in the room. The platform's job is to send the work out, capture the voice and keep recordings, reference scores and feedback where they can be reviewed. After class, students can fall back on self-directed practice and word books — but that is a fallback, not the main line.",
            })}
          </p>
        </header>

        <section className="mt-10 lg:mt-14">
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "一节课大概是这样", en: "How a lesson runs" })}
          </h2>
          <ol className="mt-5 grid gap-4 sm:grid-cols-3">
            {lessonSteps.map((step) => (
              <li key={step.number} className={`${CARD} h-full`}>
                <span
                  className="font-['Iowan_Old_Style','Palatino_Linotype',Georgia,serif] text-xl italic text-tan-sepia dark:text-tan"
                  aria-hidden="true"
                >
                  {step.number}
                </span>
                <h3 className="mt-1 text-base font-semibold">{step.title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {step.body}
                </p>
              </li>
            ))}
          </ol>
        </section>

        <section className="mt-10 lg:mt-14">
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "平台能做的事", en: "What the platform covers" })}
          </h2>
          <div className="mt-5 grid gap-4 lg:grid-cols-3">
            {capabilities.map((item) => (
              <article key={item.title} className={CARD}>
                <item.icon
                  className="size-5 text-tan-umber dark:text-tan"
                  aria-hidden="true"
                />
                <h3 className="mt-3 text-base font-semibold">{item.title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {item.body}
                </p>
              </article>
            ))}
          </div>
          <p className="mt-4 text-sm leading-6 text-muted-foreground">
            {t({
              zh: "此外还有背单词（五级词书、看义拼写、错词本）、模考（逐题限时）、班级与个人学情报告导出。",
              en: "On top of that: vocabulary work (five-level word books, meaning-and-spelling drills, a wrong-word book), timed mock exams, and class or individual reports you can export.",
            })}
          </p>
        </section>

        <section className="mt-10 lg:mt-14">
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "分数怎么读", en: "How to read the scores" })}
          </h2>
          <div className="mt-5 max-w-[52rem] space-y-3 text-sm leading-7 text-muted-foreground">
            <p>
              {t({
                zh: "界面上出现的分数都是练习参考：跟读类给出引擎的三维分，问答类给出总评与建议，另有独立的模拟分。",
                en: "Every number in the interface is a practice reference: read-aloud and repeat tasks show the engine's three dimensions, Q&A shows an overall comment plus suggestions, and rubric-based mock scores are shown separately.",
              })}
            </p>
            <p>
              {t({
                zh: "不同来源（跟读引擎、模型建议、词表口径）在界面上分开标注，方便老师判断哪一部分值得信、哪一部分只能当提示。",
                en: "Sources — repeat engine, model suggestions, word-list level — are labelled separately, so a teacher can tell which part is worth trusting and which is only a hint.",
              })}
            </p>
            <p className="font-medium text-foreground">
              {t({
                zh: "这些分数不是官方考试成绩，不能用于出具成绩单或对外证明。",
                en: "These scores are not official exam results and cannot be used for transcripts or external certification.",
              })}
            </p>
          </div>
        </section>

        <section className="mt-10 lg:mt-14">
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "数据边界", en: "Data boundaries" })}
          </h2>
          <ul className="mt-5 max-w-[52rem] list-disc space-y-2.5 pl-5 text-sm leading-7 text-muted-foreground marker:text-tan-umber dark:marker:text-tan">
            <li>
              {t({
                zh: "账号、班级与作答数据归属学校；平台运营方只做运维与开通，不代学校对外使用这些数据。",
                en: "Accounts, classes and attempt data belong to the school. The platform team handles operations and onboarding, and does not reuse that data on the school's behalf.",
              })}
            </li>
            <li>
              {t({
                zh: "跨校访问在应用层与数据库层同时拦截：老师看不到他校学生，学生只看得到自己的记录。",
                en: "Cross-school access is blocked at both the application and database layers: a teacher never sees another school's students, and a student only sees their own records.",
              })}
            </li>
            <li>
              {t({
                zh: "生产环境走 HTTPS；全站浏览器访问，不需要安装客户端。",
                en: "Production runs over HTTPS, entirely in the browser — no client to install.",
              })}
            </li>
          </ul>
          <p className="mt-4 text-sm">
            <Link
              to="/privacy"
              className="font-medium text-primary underline-offset-4 hover:underline"
            >
              {t({
                zh: "完整的数据与隐私说明",
                en: "Full data and privacy notes",
              })}
            </Link>
          </p>
        </section>

        <section className="mt-10 rounded-2xl bg-brand-pine p-6 text-paper-ivory sm:p-8 lg:mt-14 dark:bg-brand-pine-dark">
          <h2 className="text-xl font-semibold sm:text-2xl">
            {t({ zh: "下一步", en: "Next step" })}
          </h2>
          <p className="mt-2 max-w-[48rem] text-sm leading-6 text-paper-ivory/80">
            {t({
              zh: "想先让一个班跑一遍，看帮助页的开通与课堂流程；已经在用，直接登录。",
              en: "Want to run one class first? The help page covers onboarding and the in-class flow. Already using it? Just sign in.",
            })}
          </p>
          <div className="mt-5 flex flex-col gap-3 sm:flex-row">
            <Link
              to="/help"
              className="inline-flex min-h-11 items-center justify-center rounded-xl bg-tan-soft px-5 text-sm font-semibold text-brand-ink transition-colors hover:bg-tan-pale"
            >
              {t({ zh: "查看使用帮助", en: "Read the help guide" })}
              <ArrowRight className="ml-1.5 size-4" aria-hidden="true" />
            </Link>
            <Link
              to="/login"
              className="inline-flex min-h-11 items-center justify-center rounded-xl border border-white/30 px-5 text-sm font-semibold text-paper-ivory transition-colors hover:bg-white/10"
            >
              {t({ zh: "登录", en: "Sign in" })}
            </Link>
          </div>
        </section>
      </article>
    </SiteShell>
  )
}
