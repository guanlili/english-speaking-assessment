import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowRight, KeyRound, Mic, ShieldCheck } from "lucide-react"

import { SiteShell } from "@/components/Site/SiteShell"
import { APP_NAME, SUPPORT_EMAIL } from "@/config"
import { useI18n } from "@/lib/i18n"

export const Route = createFileRoute("/help")({
  component: HelpPage,
  head: () => ({
    meta: [
      { title: `使用帮助 / Help - ${APP_NAME}` },
      {
        name: "description",
        content:
          "登录入口、学生进入课堂、麦克风与录音、忘记密码、参考分说明与常见问题。",
      },
    ],
  }),
})

const CARD =
  "rounded-2xl border border-brand-ink/12 bg-paper-card p-5 dark:border-border dark:bg-card"
const EYEBROW =
  "mb-3 flex items-center gap-2.5 text-[11px] font-semibold tracking-[0.16em] text-muted-foreground"
const HAIRLINE = "h-px w-7 bg-tan-umber dark:bg-tan"

function HelpPage() {
  const { t } = useI18n()

  const starts = [
    {
      icon: KeyRound,
      title: t({ zh: "老师／学校管理员", en: "Teacher / admin" }),
      body: t({
        zh: "打开登录页，用学校邮箱与密码登录；学校有专属地址时，用那个地址会显示学校名称。",
        en: "Open the sign-in page and use your school email and password. If your school has its own address, signing in there shows the school name.",
      }),
      to: "/login" as const,
      cta: t({ zh: "去登录", en: "Sign in" }),
    },
    {
      icon: Mic,
      title: t({ zh: "学生", en: "Student" }),
      body: t({
        zh: "用学号与密码登录，或直接打开老师发的课堂链接；第一次进入课堂要允许麦克风。",
        en: "Sign in with your student ID and password, or open the class link your teacher sent. Allow the microphone the first time you enter.",
      }),
      to: "/join" as const,
      cta: t({ zh: "进入课堂", en: "Enter class" }),
    },
    {
      icon: ShieldCheck,
      title: t({ zh: "学校专属入口", en: "School entry" }),
      body: t({
        zh: "每所学校有一个带学校标识的登录地址，找不到就用通用登录页按邮箱进入。",
        en: "Each school has a sign-in address that carries its identifier. Can't find it? The general sign-in page with your email works too.",
      }),
      to: "#school-entry" as const,
      cta: t({ zh: "看说明", en: "See details" }),
    },
  ]

  const faqs = [
    {
      q: t({
        zh: "课堂链接打不开，提示页面不存在。",
        en: "The class link shows page not found.",
      }),
      a: t({
        zh: "课堂可能已被删除或重建，旧链接随之失效。向老师要新的课堂码或链接即可，不要在旧链接上反复尝试。",
        en: "The class may have been deleted or recreated, which retires the old link. Ask your teacher for the new class code or link instead of retrying the old one.",
      }),
    },
    {
      q: t({
        zh: "点了麦克风没反应，或者一直录不上。",
        en: "The microphone does nothing, or recording never starts.",
      }),
      a: t({
        zh: "先在设备检查页允许声音与麦克风；浏览器里被拒绝过一次后要在站点设置里手动恢复。iPad 上用 Safari 或 Chrome 的较新版本，插上耳机能明显减少回声。",
        en: "Allow sound and microphone on the device check page first. If you denied it once, restore it in the browser's site settings. On iPad use a recent Safari or Chrome, and headphones noticeably reduce echo.",
      }),
    },
    {
      q: t({ zh: "忘记密码怎么办？", en: "I forgot my password." }),
      a: t({
        zh: "登录页有「找回密码」，按邮箱收信重置。学生账号由老师或学校管理员在成员管理里重置，默认初始密码由学校统一约定。",
        en: "Use “recover password” on the sign-in page to reset by email. Student accounts are reset by a teacher or school admin in member management; the school sets the default initial password.",
      }),
    },
    {
      q: t({
        zh: "分数为什么是这个数？算不算成绩？",
        en: "Why this score? Does it count as a grade?",
      }),
      a: t({
        zh: "界面上的分数都是练习参考：跟读类给引擎分，问答类给总评与建议，另有模拟分。它不是官方考试成绩，不能用于成绩单或对外证明。",
        en: "All scores are practice references: engine scores for read-aloud and repeat, an overall comment plus suggestions for Q&A, and separate rubric mock scores. They are not official results and cannot be used for transcripts or certification.",
      }),
    },
    {
      q: t({
        zh: "老师后来改了题库，之前发布的练习会变吗？",
        en: "The teacher edited the question bank — does previous work change?",
      }),
      a: t({
        zh: "不会。已发布的练习按发布当时的题目快照解释，题库编辑只影响下一次发布，历史作答与结果保持原样。",
        en: "No. Published practice is read from the snapshot taken at publishing time; bank edits only affect the next release, and past attempts stay as they were.",
      }),
    },
    {
      q: t({
        zh: "换设备或换浏览器，进度会丢吗？",
        en: "Will I lose progress on another device?",
      }),
      a: t({
        zh: "用同一个学号登录，练习与成绩跟着账号走。设备上缓存的班级身份只在本机有效，换设备后重新进一次班即可。",
        en: "Sign in with the same student ID and your work follows the account. The cached class identity is local to one device, so re-enter the class once on a new one.",
      }),
    },
    {
      q: t({
        zh: "一个学生同时在几个班，记录会混在一起吗？",
        en: "I'm in several classes — do records mix?",
      }),
      a: t({
        zh: "不会。登录后进入「我的班级」选班，各班任务与成长分别记录，顶部只给账号合计。",
        en: "No. After signing in, pick a class on “My Classes”; tasks and growth are tracked per class, with only an account total at the top.",
      }),
    },
    {
      q: t({
        zh: "学校被停用后会怎样？",
        en: "What happens if the school is disabled?",
      }),
      a: t({
        zh: "该校所有账号（包括已登录的会话）立即失效，需要联系学校管理员与平台运营方恢复。",
        en: "Every account at that school — including sessions already signed in — stops working immediately. Contact the school admin and the platform team to restore it.",
      }),
    },
  ]

  return (
    <SiteShell>
      <div className="mx-auto max-w-[1440px] px-5 pt-10 sm:px-10 lg:px-16 lg:pt-14">
        <header className="page-enter max-w-[58rem]">
          <p className={EYEBROW}>
            <span className={HAIRLINE} aria-hidden="true" />
            {t({ zh: "使用帮助", en: "HELP" })}
          </p>
          <h1 className="text-[28px] font-semibold leading-tight tracking-tight sm:text-4xl">
            {t({
              zh: "从登录到第一堂课",
              en: "From sign-in to your first lesson",
            })}
          </h1>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            {t({
              zh: "先按自己的身份选一条路：老师和管理员走学校登录，学生用学号登录或打开课堂链接。遇到具体问题，往下看常见问题。",
              en: "Pick the path that matches you: teachers and admins sign in through the school, students sign in with their student ID or open a class link. Specific issues are answered in the FAQ below.",
            })}
          </p>
        </header>

        <section className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {starts.map((item) => (
            <article key={item.title} className={`${CARD} h-full`}>
              <item.icon
                className="size-5 text-tan-umber dark:text-tan"
                aria-hidden="true"
              />
              <h2 className="mt-3 text-base font-semibold">{item.title}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {item.body}
              </p>
              {item.to === "#school-entry" ? (
                <a
                  href="#school-entry"
                  className="mt-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-primary underline-offset-4 hover:underline"
                >
                  {item.cta}
                  <ArrowRight className="size-4" aria-hidden="true" />
                </a>
              ) : (
                <Link
                  to={item.to}
                  className="mt-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-primary underline-offset-4 hover:underline"
                >
                  {item.cta}
                  <ArrowRight className="size-4" aria-hidden="true" />
                </Link>
              )}
            </article>
          ))}
        </section>

        <section className="mt-10 lg:mt-14">
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "四种登录方式", en: "Four ways to sign in" })}
          </h2>
          <div className="mt-4 max-w-[60rem] overflow-x-auto">
            <table className="w-full min-w-[34rem] border-collapse text-sm">
              <thead>
                <tr className="border-b border-brand-ink/12 text-left dark:border-border">
                  <th className="py-2.5 pr-4 font-semibold">
                    {t({ zh: "入口", en: "Entry" })}
                  </th>
                  <th className="py-2.5 pr-4 font-semibold">
                    {t({ zh: "谁用", en: "Who" })}
                  </th>
                  <th className="py-2.5 font-semibold">
                    {t({ zh: "说明", en: "Notes" })}
                  </th>
                </tr>
              </thead>
              <tbody className="text-muted-foreground">
                <tr className="border-b border-brand-ink/10 dark:border-border">
                  <td className="py-3 pr-4 font-mono text-xs">/login</td>
                  <td className="py-3 pr-4">
                    {t({
                      zh: "教师、学校管理员",
                      en: "Teachers, school admins",
                    })}
                  </td>
                  <td className="py-3">
                    {t({
                      zh: "通用登录页：教师用邮箱，学生切到「学生登录」用学号。",
                      en: "General page: teachers use email, students switch to the student tab and use their ID.",
                    })}
                  </td>
                </tr>
                <tr className="border-b border-brand-ink/10 dark:border-border">
                  <td className="py-3 pr-4 font-mono text-xs">
                    /s/{"{school}"}/login
                  </td>
                  <td className="py-3 pr-4">
                    {t({ zh: "某所学校的人", en: "Members of one school" })}
                  </td>
                  <td className="py-3">
                    {t({
                      zh: "学校专属入口，页面上显示学校名称，账号只在所辖学校内查找。",
                      en: "School-specific entry: shows the school name and only looks up accounts inside that school.",
                    })}
                  </td>
                </tr>
                <tr className="border-b border-brand-ink/10 dark:border-border">
                  <td className="py-3 pr-4 font-mono text-xs">
                    /platform/login
                  </td>
                  <td className="py-3 pr-4">
                    {t({ zh: "平台运营方", en: "Platform team" })}
                  </td>
                  <td className="py-3">
                    {t({
                      zh: "运营专用，只能进平台管理台，不能进学校业务。学校师生用不到这个入口。",
                      en: "Operations only: it opens the platform console, not school workspaces. Schools never need it.",
                    })}
                  </td>
                </tr>
                <tr>
                  <td className="py-3 pr-4 font-mono text-xs">/j/{"{code}"}</td>
                  <td className="py-3 pr-4">
                    {t({ zh: "学生（课堂链接）", en: "Students (class link)" })}
                  </td>
                  <td className="py-3">
                    {t({
                      zh: "老师发的课堂链接，打开后登录并直接进入该课堂。",
                      en: "The class link from your teacher: sign in and land straight in that class.",
                    })}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground sm:hidden">
            {t({
              zh: "可左右滑动查看整张表",
              en: "Swipe sideways to see the full table",
            })}
          </p>
        </section>

        <section className="mt-10 lg:mt-14">
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "学生进入课堂的三步", en: "Three steps into class" })}
          </h2>
          <ol className="mt-5 grid gap-4 sm:grid-cols-3">
            {[
              {
                n: "01",
                t: t({ zh: "拿到课堂码", en: "Get the class code" }),
                b: t({
                  zh: "老师在课上给出课堂码，或者直接发课堂链接。",
                  en: "Your teacher gives a class code in the room, or sends the class link.",
                }),
              },
              {
                n: "02",
                t: t({ zh: "登录并进班", en: "Sign in and enter" }),
                b: t({
                  zh: "用学号登录后进入课堂；链接方式会直接落到这个班。",
                  en: "Sign in with your student ID and enter; a link lands you in that class directly.",
                }),
              },
              {
                n: "03",
                t: t({ zh: "允许麦克风", en: "Allow the microphone" }),
                b: t({
                  zh: "第一次作答前做一次设备检查，允许声音与麦克风后按题目顺序自动推进。",
                  en: "Run the device check once before answering: allow sound and microphone, then items advance in order.",
                }),
              },
            ].map((step) => (
              <li key={step.n} className={CARD}>
                <span
                  className="font-['Iowan_Old_Style','Palatino_Linotype',Georgia,serif] text-xl italic text-tan-sepia dark:text-tan"
                  aria-hidden="true"
                >
                  {step.n}
                </span>
                <h3 className="mt-1 text-base font-semibold">{step.t}</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {step.b}
                </p>
              </li>
            ))}
          </ol>
        </section>

        <section id="school-entry" className="mt-10 scroll-mt-24 lg:mt-14">
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "学校专属入口怎么找", en: "Finding your school entry" })}
          </h2>
          <div className="mt-4 max-w-[56rem] space-y-3 text-sm leading-7 text-muted-foreground">
            <p>
              {t({
                zh: "专属入口的地址形如 /s/学校标识/login，学校标识由平台开通时设定（例如学校简称的英文）。老师与管理员通常会收到完整链接。",
                en: "A school entry looks like /s/school-id/login, where the school id was set when the school was created (often the English abbreviation). Teachers and admins usually receive the full link.",
              })}
            </p>
            <p>
              {t({
                zh: "找不到专属链接时不必卡住：直接用通用登录页 /login 用邮箱登录，权限与数据都按你的学校判定，与专属入口一致。",
                en: "If you can't find it, don't get stuck: sign in with your email on the general /login page. Permissions and data are resolved by your school exactly as they are on the school entry.",
              })}
            </p>
          </div>
        </section>

        <section className="mt-10 lg:mt-14">
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "常见问题", en: "FAQ" })}
          </h2>
          <dl className="mt-5 max-w-[62rem] divide-y divide-brand-ink/10 dark:divide-border">
            {faqs.map((item) => (
              <div key={item.q} className="py-4">
                <dt className="text-sm font-semibold">{item.q}</dt>
                <dd className="mt-1.5 text-sm leading-6 text-muted-foreground">
                  {item.a}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        <section
          id="contact"
          className="mt-10 scroll-mt-24 rounded-2xl border border-brand-ink/12 bg-paper-warm/60 p-6 sm:p-8 lg:mt-14 dark:border-border dark:bg-secondary/20"
        >
          <h2 className="text-xl font-semibold sm:text-2xl">
            {t({ zh: "还没解决？", en: "Still stuck?" })}
          </h2>
          <p className="mt-2 max-w-[52rem] text-sm leading-6 text-muted-foreground">
            {t({
              zh: "课堂现场问题优先找任课老师；账号、班级与数据问题找学校的平台管理员。学校开通、批量建号与培训由平台运营方对接。",
              en: "For issues in the room, ask the teacher first. For accounts, classes and data, ask your school's platform administrator. Onboarding, bulk accounts and training go through the platform team.",
            })}
          </p>
          {SUPPORT_EMAIL !== "" && (
            <a
              href={`mailto:${SUPPORT_EMAIL}`}
              className="mt-4 inline-flex min-h-11 items-center text-sm font-medium text-tan-sepia underline-offset-4 hover:underline dark:text-tan"
            >
              {SUPPORT_EMAIL}
            </a>
          )}
          <div className="mt-4 flex flex-col gap-3 sm:flex-row">
            <Link
              to="/login"
              className="inline-flex min-h-11 items-center justify-center rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground"
            >
              {t({ zh: "去登录", en: "Sign in" })}
            </Link>
            <Link
              to="/about"
              className="inline-flex min-h-11 items-center justify-center rounded-xl border border-brand-ink/20 px-5 text-sm font-medium dark:border-border"
            >
              {t({ zh: "了解平台", en: "About the platform" })}
            </Link>
          </div>
        </section>
      </div>
    </SiteShell>
  )
}
