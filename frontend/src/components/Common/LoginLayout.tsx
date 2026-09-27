import { ArrowUpRight, AudioLines, Check, Mic } from "lucide-react"
import type { ReactNode } from "react"
import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { APP_NAME } from "@/config"

export function LoginLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-svh bg-[#f8f9f5] dark:bg-background">
      <header className="mx-auto flex max-w-[1440px] items-center justify-between px-4 py-4 sm:px-10 lg:px-16 lg:py-6">
        <Logo asLink={false} />
        <div className="flex items-center gap-5">
          <span className="hidden text-xs tracking-wider text-muted-foreground sm:block">
            每一次开口，都是进步
          </span>
          <Appearance />
        </div>
      </header>

      <main className="mx-auto grid max-w-[1440px] items-center gap-10 px-4 pb-6 pt-2 sm:px-10 lg:min-h-[calc(100svh-172px)] lg:grid-cols-[1.1fr_1fr] lg:gap-16 lg:px-16 lg:py-8 xl:gap-24">
        <section
          className="relative hidden lg:block lg:py-6"
          aria-labelledby="login-intro"
        >
          <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-primary/15 bg-secondary/60 px-3 py-1.5 text-xs font-medium text-secondary-foreground">
            <span className="size-1.5 rounded-full bg-primary" />
            为每一堂英语口语课而来
          </div>
          <h1
            id="login-intro"
            className="text-4xl font-semibold leading-[1.25] tracking-tight sm:text-5xl xl:text-6xl"
          >
            自信表达，
            <br />从
            <span className="relative inline-block text-primary">
              开口说
              <span className="absolute -bottom-2 left-0 h-1.5 w-full -rotate-2 rounded-full bg-[#efbd84]/70" />
            </span>
            开始。
          </h1>
          <p className="mt-7 max-w-sm text-sm leading-7 text-muted-foreground sm:text-base">
            跟随课堂节奏，练习真实表达。
            <br />
            让每一次小小的尝试，汇成看得见的成长。
          </p>

          <div className="relative mt-10 hidden max-w-[510px] sm:block">
            <div
              className="absolute -right-4 -top-4 size-28 rounded-full border border-primary/10"
              aria-hidden="true"
            />
            <div className="relative overflow-hidden rounded-[28px] bg-[#204f40] p-7 text-white shadow-xl shadow-[#204f40]/10 xl:p-8">
              <div
                className="absolute -bottom-28 -right-20 size-72 rounded-full border-[40px] border-white/5"
                aria-hidden="true"
              />
              <div className="relative flex items-center justify-between">
                <span className="flex items-center gap-2 text-xs tracking-[0.16em] text-[#cee2d6]">
                  <AudioLines className="size-4" /> SPEAK. CONNECT. GROW.
                </span>
                <ArrowUpRight className="size-5 text-[#cee2d6]" />
              </div>
              <p className="relative mt-9 text-3xl font-medium leading-snug tracking-tight xl:text-4xl">
                Every voice
                <br />
                has a story.
              </p>
              <p className="relative mt-3 text-sm text-[#cee2d6]">
                你的声音，值得被听见。
              </p>
              <div className="relative mt-8 flex items-center gap-4 rounded-2xl border border-white/15 bg-white/10 p-4">
                <span className="grid size-11 shrink-0 place-items-center rounded-full bg-[#e9c99d] text-[#204f40]">
                  <Mic className="size-5" />
                </span>
                <div
                  className="flex flex-1 items-center justify-between gap-1"
                  aria-hidden="true"
                >
                  {Array.from({ length: 27 }, (_, index) => (
                    <span
                      key={`wave-${index}`}
                      className={`w-1 rounded-full bg-[#c9decf] ${["h-3", "h-5", "h-8", "h-4", "h-6", "h-9", "h-5"][index % 7]}`}
                    />
                  ))}
                </div>
                <span className="text-xs text-[#cee2d6]">开口，就现在</span>
              </div>
            </div>
            <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
              {["课堂同步", "口语练习", "成长反馈"].map((item) => (
                <span key={item} className="flex items-center gap-1.5">
                  <Check className="size-3.5 text-primary" />
                  {item}
                </span>
              ))}
            </div>
          </div>
        </section>

        <section
          aria-label="登录 SpeakUp"
          className="mx-auto w-full max-w-[480px] rounded-[28px] border border-border/80 bg-card p-5 shadow-[0_16px_64px_-24px_rgba(32,79,64,0.18)] sm:p-9 lg:mx-0 lg:justify-self-end xl:p-10"
        >
          {children}
        </section>
      </main>
      <footer className="px-6 pb-6 text-center text-xs text-muted-foreground">
        © {new Date().getFullYear()} {APP_NAME} · 让表达自然发生
      </footer>
    </div>
  )
}
