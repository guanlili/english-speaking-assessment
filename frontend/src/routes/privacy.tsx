import { createFileRoute, Link } from "@tanstack/react-router"

import { SiteShell } from "@/components/Site/SiteShell"
import { APP_NAME, SUPPORT_EMAIL } from "@/config"
import { useI18n } from "@/lib/i18n"
import { publicPageHead } from "@/lib/site-meta"

export const Route = createFileRoute("/privacy")({
  component: PrivacyPage,
  head: () =>
    publicPageHead({
      path: "/privacy",
      title: `隐私与数据说明 / Privacy - ${APP_NAME}`,
      description:
        "平台保存哪些数据、谁能看到、用来做什么、如何导出与删除。账号与数据归属学校。",
    }),
})

const SECTION = "mt-9 scroll-mt-24 lg:mt-12"
const CARD =
  "rounded-2xl border border-brand-ink/12 bg-paper-card p-5 dark:border-border dark:bg-card"
const EYEBROW =
  "mb-3 flex items-center gap-2.5 text-[11px] font-semibold tracking-[0.16em] text-muted-foreground"
const HAIRLINE = "h-px w-7 bg-tan-umber dark:bg-tan"

function PrivacyPage() {
  const { t } = useI18n()

  const collected = [
    {
      title: t({ zh: "账号信息", en: "Account details" }),
      body: t({
        zh: "姓名、学号或邮箱、所属学校与班级、角色。密码只保存哈希值，平台无法还原明文。",
        en: "Name, student ID or email, school and class, and role. Passwords are stored only as hashes; plain passwords cannot be recovered.",
      }),
    },
    {
      title: t({
        zh: "口语录音与转写",
        en: "Speech recordings and transcripts",
      }),
      body: t({
        zh: "作答时录制的音频、由音频得到的转写文本，以及评分结果。",
        en: "The audio recorded while answering, the transcript produced from it, and the resulting scores.",
      }),
    },
    {
      title: t({ zh: "学习记录", en: "Learning records" }),
      body: t({
        zh: "练习与考试的作答、成绩、词汇学习进度、错词记录，以及教师的点评与补练安排。",
        en: "Answers and results from practice and exams, vocabulary progress and wrong-word history, plus teacher feedback and follow-up assignments.",
      }),
    },
    {
      title: t({ zh: "导出文件", en: "Exports" }),
      body: t({
        zh: "教师或学生主动生成的学情报告 PDF、口语原音频 ZIP 等文件。",
        en: "Files someone chose to generate, such as student report PDFs or original audio ZIPs.",
      }),
    },
  ]

  const audiences = [
    t({
      zh: "学生本人：可以看到自己的作答、参考分、成长与词汇记录。",
      en: "The student: their own answers, reference scores, progress and vocabulary records.",
    }),
    t({
      zh: "任课教师与学校管理员：可以看到本校、本班范围内的作答、录音与学情。",
      en: "The teacher and school admin: answers, recordings and learning evidence within their own school and classes.",
    }),
    t({
      zh: "平台运营方：为开通、运维与故障处理访问数据，不代学校对外使用。",
      en: "The platform team: accesses data for onboarding, operations and troubleshooting, and does not reuse it externally on the school's behalf.",
    }),
    t({
      zh: "其他学校：任何跨校读取与写入都被拒绝，包括列表与导出。",
      en: "Any other school: all cross-school reads and writes are refused, including lists and exports.",
    }),
  ]

  const local = [
    t({
      zh: "登录凭证（access_token）与角色标记：用于保持登录态与路由分流。",
      en: "Sign-in credential (access_token) and role marker: keeps you signed in and routes you correctly.",
    }),
    t({
      zh: "界面语言与主题偏好：记住你选的中文/英文与明暗外观。",
      en: "Language and theme preference: remembers your Chinese/English choice and light/dark appearance.",
    }),
    t({
      zh: "本机班级身份：记住你在某台设备上进入过哪个课堂，便于直接回到课堂。",
      en: "Local class identity: remembers which class this device entered, so you can return directly.",
    }),
    t({
      zh: "清除浏览器数据会一并清掉以上内容，不会影响服务端已保存的作答与成绩。",
      en: "Clearing browser data removes all of the above; it does not touch attempts and scores already saved on the server.",
    }),
  ]

  return (
    <SiteShell>
      <div className="mx-auto max-w-[1440px] px-5 pt-10 sm:px-10 lg:px-16 lg:pt-14">
        <header className="page-enter max-w-[58rem]">
          <p className={EYEBROW}>
            <span className={HAIRLINE} aria-hidden="true" />
            {t({ zh: "隐私与数据说明", en: "PRIVACY & DATA" })}
          </p>
          <h1 className="text-[28px] font-semibold leading-tight tracking-tight sm:text-4xl">
            {t({
              zh: "学生的声音，只为教学服务。",
              en: "Student voices, only for teaching.",
            })}
          </h1>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            {t({
              zh: "这个平台会保存口语录音，所以有必要把「存了什么、谁能看到、怎么删」写清楚。账号与数据归属学校，具体保存期限与处理流程由学校与平台运营方约定。",
              en: "The platform stores spoken audio, so it is worth stating plainly what is kept, who can see it, and how it is removed. Accounts and data belong to the school; retention and handling are agreed between the school and the platform team.",
            })}
          </p>
        </header>

        <section className={SECTION}>
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "保存哪些数据", en: "What we store" })}
          </h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {collected.map((item) => (
              <article key={item.title} className={CARD}>
                <h3 className="text-base font-semibold">{item.title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {item.body}
                </p>
              </article>
            ))}
          </div>
        </section>

        <section className={SECTION}>
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "谁能看到", en: "Who can see it" })}
          </h2>
          <ul className="mt-4 max-w-[58rem] space-y-2.5 text-sm leading-7 text-muted-foreground">
            {audiences.map((line) => (
              <li key={line} className="flex gap-2.5">
                <span
                  className="mt-2 h-px w-4 shrink-0 bg-tan-umber dark:bg-tan"
                  aria-hidden="true"
                />
                {line}
              </li>
            ))}
          </ul>
        </section>

        <section className={SECTION}>
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "麦克风与录音", en: "Microphone and recording" })}
          </h2>
          <div className="mt-4 max-w-[58rem] space-y-3 text-sm leading-7 text-muted-foreground">
            <p>
              {t({
                zh: "平台只在作答时申请麦克风，不申请摄像头。拒绝授权不会导致账号异常，但无法完成需要录音的题目。",
                en: "The platform asks for the microphone only while answering, and never for the camera. Declining does not break your account, but tasks that need recording cannot be completed.",
              })}
            </p>
            <p>
              {t({
                zh: "录音地址使用随机标识，无法靠猜访问；只有具备相应权限的教师或管理员能回放。",
                en: "Recording addresses use random identifiers that cannot be guessed, and only teachers or admins with the right permission can play them back.",
              })}
            </p>
          </div>
        </section>

        <section className={SECTION}>
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({
              zh: "浏览器本地保存的内容",
              en: "What stays in your browser",
            })}
          </h2>
          <ul className="mt-4 max-w-[58rem] space-y-2.5 text-sm leading-7 text-muted-foreground">
            {local.map((line) => (
              <li key={line} className="flex gap-2.5">
                <span
                  className="mt-2 h-px w-4 shrink-0 bg-tan-umber dark:bg-tan"
                  aria-hidden="true"
                />
                {line}
              </li>
            ))}
          </ul>
        </section>

        <section className={SECTION}>
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "安全措施", en: "Safeguards" })}
          </h2>
          <div className="mt-4 max-w-[58rem] space-y-3 text-sm leading-7 text-muted-foreground">
            <p>
              {t({
                zh: "生产环境全程 HTTPS 传输；账号密码以哈希保存。",
                en: "Production traffic is HTTPS end to end, and passwords are stored as hashes.",
              })}
            </p>
            <p>
              {t({
                zh: "数据库按学校启用行级安全，跨校数据在物理查询层就不可见；学校被停用时，该校已登录会话立即失效。",
                en: "The database enforces row-level security per school, so cross-school data is invisible at the query layer; when a school is disabled, its signed-in sessions stop working immediately.",
              })}
            </p>
            <p>
              {t({
                zh: "平台的运维巡检只检查服务可用性与磁盘占用，不采集学生作答内容。",
                en: "Operational monitoring checks service availability and disk usage only; it never collects student answers.",
              })}
            </p>
          </div>
        </section>

        <section className={SECTION}>
          <h2 className="text-2xl font-semibold tracking-tight">
            {t({ zh: "导出与删除", en: "Export and removal" })}
          </h2>
          <div className="mt-4 max-w-[58rem] space-y-3 text-sm leading-7 text-muted-foreground">
            <p>
              {t({
                zh: "学生可在「下载中心」取回教师为自己生成的报告；教师可导出班级学情与口语原音频。",
                en: "Students can collect reports a teacher generated for them in the download center; teachers can export class evidence and original audio.",
              })}
            </p>
            <p>
              {t({
                zh: "删除账号或作答数据需要走学校渠道：先联系学校平台管理员，由学校与平台运营方确认范围后执行。平台不接受绕过学校的个人删除请求，因为数据归属学校。",
                en: "Removing an account or attempts goes through the school: contact the school's platform administrator, and the school confirms scope with the platform team. Individual requests that bypass the school are not accepted, because the data belongs to the school.",
              })}
            </p>
          </div>
        </section>

        <section
          id="contact"
          className="mt-9 scroll-mt-24 rounded-2xl border border-brand-ink/12 bg-paper-warm/60 p-6 sm:p-8 lg:mt-12 dark:border-border dark:bg-secondary/20"
        >
          <h2 className="text-xl font-semibold sm:text-2xl">
            {t({ zh: "关于这份说明", en: "About this note" })}
          </h2>
          <p className="mt-2 max-w-[52rem] text-sm leading-6 text-muted-foreground">
            {t({
              zh: "这份说明讲的是平台的技术行为，不替代学校与家长之间的约定。涉及具体学生的处理，请先与学校管理员沟通。",
              en: "This note describes the platform's technical behaviour; it does not replace agreements between schools and families. For anything involving a specific student, start with the school administrator.",
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
              to="/help"
              className="inline-flex min-h-11 items-center justify-center rounded-xl border border-brand-ink/20 px-5 text-sm font-medium dark:border-border"
            >
              {t({ zh: "使用帮助", en: "Help guide" })}
            </Link>
            <Link
              to="/about"
              className="inline-flex min-h-11 items-center justify-center rounded-xl border border-brand-ink/20 px-5 text-sm font-medium dark:border-border"
            >
              {t({ zh: "关于平台", en: "About the platform" })}
            </Link>
          </div>
        </section>
      </div>
    </SiteShell>
  )
}
