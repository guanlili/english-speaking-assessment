import { Link } from "@tanstack/react-router"
import type { ReactNode } from "react"

import { Appearance } from "@/components/Common/Appearance"
import { LanguageToggle } from "@/components/Common/LanguageToggle"
import { Logo } from "@/components/Common/Logo"
import { Button } from "@/components/ui/button"
import { APP_NAME, SUPPORT_EMAIL } from "@/config"
import { useI18n } from "@/lib/i18n"

/**
 * 公开站点外壳（落地页 / 关于 / 帮助 / 隐私）。
 *
 * 与登录页同一套视觉语言（paper 底 + brand-pine 深底 + tan 点缀），
 * 但多了三项学校方需要的东西：站点导航、页脚（法务/入口/联系）与首屏跳转链接。
 * 这些页面不依赖登录态，未登录用户、搜索引擎与第一次拿到域名的老师都能直接看。
 */
export function SiteShell({ children }: { children: ReactNode }) {
  const { t } = useI18n()

  return (
    <div className="min-h-svh bg-paper font-['Avenir_Next','PingFang_SC','Hiragino_Sans_GB','Microsoft_YaHei',sans-serif] text-brand-ink dark:bg-background dark:text-foreground">
      <a className="skip-link" href="#site-main">
        {t({ zh: "跳到主要内容", en: "Skip to main content" })}
      </a>

      <header className="border-b border-brand-ink/10 dark:border-border">
        <div className="mx-auto flex max-w-[1440px] items-center gap-3 px-5 py-4 sm:px-10 lg:px-16">
          <Logo />
          <div className="ml-auto flex items-center gap-2 sm:gap-4">
            <nav
              aria-label={t({ zh: "站点导航", en: "Site navigation" })}
              className="hidden items-center gap-1 sm:flex"
            >
              <Link
                to="/about"
                className="rounded-lg px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {t({ zh: "关于平台", en: "About" })}
              </Link>
              <Link
                to="/help"
                className="rounded-lg px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {t({ zh: "使用帮助", en: "Help" })}
              </Link>
            </nav>
            <LanguageToggle />
            {/* 手机宽度下 Logo + 语言切换 + 登录已经占满一行，外观切换让位给页脚/系统设置 */}
            <span className="hidden sm:block">
              <Appearance />
            </span>
            <Button asChild size="sm">
              <Link to="/login">{t({ zh: "登录", en: "Sign in" })}</Link>
            </Button>
          </div>
        </div>
      </header>

      <main id="site-main">{children}</main>

      <SiteFooter />
    </div>
  )
}

function SiteFooter() {
  const { t } = useI18n()

  return (
    <footer className="mt-16 border-t border-brand-ink/10 bg-paper-warm/50 dark:border-border dark:bg-secondary/20">
      <div className="mx-auto grid max-w-[1440px] gap-9 px-5 py-10 sm:grid-cols-2 sm:px-10 lg:grid-cols-[minmax(0,1.5fr)_repeat(3,minmax(0,1fr))] lg:gap-12 lg:px-16">
        <div>
          <Logo asLink={false} />
          <p className="mt-4 max-w-[26rem] text-sm leading-6 text-muted-foreground">
            {t({
              zh: "面向学校的英语口语课堂工具：老师发布练习，全班同步开口，作答留下录音、参考分与教师点评。",
              en: "A classroom tool for spoken English in schools: teachers publish practice, the whole class speaks together, and every answer keeps its recording, reference score and teacher feedback.",
            })}
          </p>
          <p className="mt-3 max-w-[26rem] text-xs leading-5 text-muted-foreground">
            {t({
              zh: "界面里的分数均为练习参考，不是官方考试成绩。",
              en: "Scores shown in the platform are practice references, not official exam results.",
            })}
          </p>
        </div>

        <nav aria-label={t({ zh: "平台", en: "Platform" })}>
          <h2 className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">
            {t({ zh: "平台", en: "PLATFORM" })}
          </h2>
          <ul className="mt-3 space-y-2.5 text-sm">
            <li>
              <Link
                to="/about"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                {t({ zh: "关于平台", en: "About" })}
              </Link>
            </li>
            <li>
              <Link
                to="/help"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                {t({ zh: "使用帮助", en: "Help" })}
              </Link>
            </li>
            <li>
              <Link
                to="/privacy"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                {t({ zh: "隐私说明", en: "Privacy" })}
              </Link>
            </li>
          </ul>
        </nav>

        <nav aria-label={t({ zh: "入口", en: "Entry points" })}>
          <h2 className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">
            {t({ zh: "入口", en: "ENTRY" })}
          </h2>
          <ul className="mt-3 space-y-2.5 text-sm">
            <li>
              <Link
                to="/login"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                {t({ zh: "教师与管理员登录", en: "Teacher & admin sign in" })}
              </Link>
            </li>
            <li>
              <Link
                to="/join"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                {t({ zh: "学生进入课堂", en: "Students enter class" })}
              </Link>
            </li>
            <li>
              <Link
                to="/help"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                {t({ zh: "学校专属入口怎么找", en: "Find your school entry" })}
              </Link>
            </li>
          </ul>
        </nav>

        <div>
          <h2 className="text-[11px] font-semibold tracking-[0.16em] text-muted-foreground">
            {t({ zh: "支持", en: "SUPPORT" })}
          </h2>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            {t({
              zh: "开通学校空间、批量建号或课堂现场问题，请联系你所在学校的平台管理员。",
              en: "For school onboarding, bulk accounts or in-class support, please contact your school's platform administrator.",
            })}
          </p>
          {SUPPORT_EMAIL !== "" && (
            <a
              href={`mailto:${SUPPORT_EMAIL}`}
              className="mt-4 inline-flex min-h-11 items-center font-medium text-tan-sepia underline-offset-4 hover:underline dark:text-tan"
            >
              {SUPPORT_EMAIL}
            </a>
          )}
        </div>
      </div>

      <div className="border-t border-brand-ink/10 dark:border-border">
        <div className="mx-auto flex max-w-[1440px] flex-col gap-1 px-5 py-5 text-[11px] tracking-wide text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-10 lg:px-16">
          <span>
            © {new Date().getFullYear()} {APP_NAME}
          </span>
          <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <Link to="/privacy" className="hover:text-foreground">
              {t({ zh: "隐私说明", en: "Privacy" })}
            </Link>
            <span lang="en">A little practice. A little braver.</span>
          </span>
        </div>
      </div>
    </footer>
  )
}
