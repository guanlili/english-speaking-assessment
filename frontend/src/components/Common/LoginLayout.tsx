import { AudioLines, Mic } from "lucide-react"
import type { ReactNode } from "react"
import { Appearance } from "@/components/Common/Appearance"
import { LanguageToggle } from "@/components/Common/LanguageToggle"
import { Logo } from "@/components/Common/Logo"
import { APP_NAME } from "@/config"
import { useI18n } from "@/lib/i18n"

export function LoginLayout({ children }: { children: ReactNode }) {
  const { t } = useI18n()
  const classroomSteps = [
    {
      number: "01",
      title: t({ zh: "进入课堂", en: "Join class" }),
      description: t({ zh: "跟随今日练习", en: "Follow today's practice" }),
    },
    {
      number: "02",
      title: t({ zh: "开口练习", en: "Speak up" }),
      description: t({ zh: "练习真实表达", en: "Practice real expression" }),
    },
    {
      number: "03",
      title: t({ zh: "回看反馈", en: "Review feedback" }),
      description: t({ zh: "找到下一步方向", en: "Find your next step" }),
    },
  ]
  return (
    <div className="min-h-svh bg-[#f7f4ed] font-['Avenir_Next','PingFang_SC','Hiragino_Sans_GB','Microsoft_YaHei',sans-serif] text-[#233e34] dark:bg-background dark:text-foreground">
      <header className="mx-auto flex max-w-[1440px] items-center justify-between px-5 py-5 sm:px-10 lg:px-16 lg:py-6">
        <Logo asLink={false} />
        <div className="flex items-center gap-6">
          <span className="hidden border-r border-[#233e34]/15 pr-6 text-xs tracking-wider text-muted-foreground sm:block dark:border-border">
            {t({ zh: "每一次开口，都是进步", en: "Every voice counts" })}
          </span>
          <LanguageToggle />
          <Appearance />
        </div>
      </header>

      <main className="mx-auto grid max-w-[1440px] items-center gap-7 px-5 pb-10 pt-4 sm:px-10 lg:min-h-[calc(100svh-152px)] lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-16 lg:px-16 lg:py-8 xl:gap-24">
        <section
          className="mx-auto w-full max-w-[480px] lg:max-w-[560px]"
          aria-labelledby="login-intro"
        >
          <p className="mb-3 flex items-center gap-2.5 text-[11px] font-semibold tracking-[0.16em] text-muted-foreground lg:mb-5">
            <span
              className="h-px w-7 bg-[#ac7048] dark:bg-[#efbd94]"
              aria-hidden="true"
            />
            {t({
              zh: "为每一堂英语口语课而来",
              en: "BUILT FOR SPOKEN ENGLISH CLASS",
            })}
          </p>
          <h1
            id="login-intro"
            className="text-[28px] font-semibold leading-[1.25] tracking-tight sm:text-3xl lg:text-[38px] xl:text-[44px]"
          >
            {t({
              zh: "让表达，自然发生。",
              en: "Speak naturally. Grow confidently.",
            })}
          </h1>
          <p className="mt-3 text-sm leading-6 text-muted-foreground lg:text-base">
            {t({
              zh: "跟随课堂节奏，练习真实表达。",
              en: "Follow your class pace and practice speaking for real.",
            })}
          </p>

          <div className="relative mt-7 hidden overflow-hidden rounded-2xl bg-[#204f40] p-7 text-[#fbf6eb] lg:block xl:p-8 dark:bg-[#193f33]">
            <div
              className="pointer-events-none absolute -right-20 top-10 size-72 rounded-full border border-[#e9c6a2]/15 before:absolute before:inset-7 before:rounded-full before:border before:border-[#e9c6a2]/15 after:absolute after:inset-14 after:rounded-full after:border after:border-[#e9c6a2]/15"
              aria-hidden="true"
            />
            <p
              className="relative flex items-center gap-2 text-[10px] font-medium tracking-[0.2em] text-[#d0ded3]"
              lang="en"
            >
              <AudioLines className="size-4" aria-hidden="true" />
              LISTEN. SPEAK. GROW.
            </p>
            <p
              className="relative mt-6 font-['Iowan_Old_Style','Palatino_Linotype',Georgia,serif] text-5xl leading-[1.05] tracking-tight xl:text-6xl"
              lang="en"
            >
              Find your
              <br />
              <span className="italic text-[#efbd94]">own voice.</span>
            </p>
            <div
              className="relative mt-7 flex items-center gap-5 border-t border-white/20 pt-5"
              aria-hidden="true"
            >
              <span className="grid size-10 shrink-0 place-items-center rounded-full border border-[#efbd94]/50 text-[#efbd94]">
                <Mic className="size-4" />
              </span>
              <div className="flex h-10 flex-1 items-center justify-between gap-1">
                {Array.from({ length: 31 }, (_, index) => (
                  <span
                    key={`wave-${index}`}
                    className={`w-1 rounded-full ${index > 10 && index < 20 ? "bg-[#efbd94]" : "bg-[#c9decf]/65"} ${["h-2", "h-4", "h-6", "h-3", "h-8", "h-10", "h-5"][index % 7]}`}
                  />
                ))}
              </div>
            </div>
          </div>

          <ol
            className="mt-6 hidden grid-cols-3 lg:grid"
            aria-label={t({
              zh: "课堂练习流程",
              en: "How class practice works",
            })}
          >
            {classroomSteps.map((step) => (
              <li
                key={step.number}
                className="border-l border-[#233e34]/15 pl-4 first:border-0 first:pl-0 dark:border-border"
              >
                <span
                  className="font-['Iowan_Old_Style',Georgia,serif] text-xl italic text-[#99603d] dark:text-[#efbd94]"
                  aria-hidden="true"
                >
                  {step.number}
                </span>
                <h2 className="mt-1 text-sm font-semibold">{step.title}</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  {step.description}
                </p>
              </li>
            ))}
          </ol>
        </section>

        <section
          aria-label={t({ zh: "登录 SpeakUp", en: "Sign in to SpeakUp" })}
          className="relative mx-auto w-full max-w-[480px] rounded-2xl border border-[#233e34]/12 bg-[#fffdf8] p-5 shadow-[0_20px_70px_-36px_rgba(32,79,64,0.28)] before:absolute before:-top-px before:left-6 before:h-[3px] before:w-12 before:bg-[#dba77b] sm:p-8 sm:before:left-9 lg:mx-0 lg:justify-self-end xl:p-10 dark:border-border dark:bg-card dark:shadow-none"
        >
          {children}
        </section>
      </main>
      <footer className="mx-auto flex max-w-[1440px] items-center justify-center px-5 pb-6 text-[11px] tracking-wide text-muted-foreground sm:justify-between sm:px-10 lg:px-16">
        <span>
          © {new Date().getFullYear()} {APP_NAME}
        </span>
        <span className="hidden sm:block" lang="en">
          A little practice. A little braver.
        </span>
      </footer>
    </div>
  )
}
