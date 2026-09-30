import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { useI18n } from "@/lib/i18n"
import { Footer } from "./Footer"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  const { t } = useI18n()
  return (
    <div className="grid min-h-svh lg:grid-cols-2">
      <div className="relative hidden flex-col justify-between bg-primary p-14 text-primary-foreground lg:flex">
        <div className="w-fit rounded-2xl bg-card p-4">
          <Logo asLink={false} />
        </div>
        <div className="max-w-lg">
          <p className="mb-6 text-xs tracking-[0.25em] opacity-70">
            A LITTLE PRACTICE. A BIG DIFFERENCE.
          </p>
          <h2 className="text-5xl font-semibold leading-tight">
            {t({ zh: "让每一种声音，", en: "Every voice," })}
            <br />
            {t({ zh: "都被听见。", en: "deserves to be heard." })}
          </h2>
          <p className="mt-6 text-base leading-8 opacity-80">
            {t({
              zh: "从一段跟读，到一次自在表达。",
              en: "From read-aloud repetition to confident expression.",
            })}
            <br />
            {t({
              zh: "连接课堂、练习与成长的英语口语学习空间。",
              en: "An English speaking space connecting class, practice, and growth.",
            })}
          </p>
          <div className="mt-10 flex gap-3 text-sm">
            <span className="rounded-full border border-white/25 px-4 py-2">
              {t({ zh: "课堂同步", en: "Classroom Sync" })}
            </span>
            <span className="rounded-full border border-white/25 px-4 py-2">
              {t({ zh: "口语练习", en: "Speaking Practice" })}
            </span>
            <span className="rounded-full border border-white/25 px-4 py-2">
              {t({ zh: "成长反馈", en: "Growth Feedback" })}
            </span>
          </div>
        </div>
        <p className="text-xs opacity-60">SPEAK A LITTLE. GROW A LOT.</p>
      </div>
      <div className="flex flex-col gap-4 p-6 md:p-10">
        <div className="flex justify-end">
          <Appearance />
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-sm">{children}</div>
        </div>
        <Footer />
      </div>
    </div>
  )
}
