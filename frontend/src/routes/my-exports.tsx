import { createFileRoute, Link, redirect } from "@tanstack/react-router"

import { LanguageToggle } from "@/components/Common/LanguageToggle"
import { Logo } from "@/components/Common/Logo"
import { ExportCenter } from "@/components/Exports/ExportCenter"
import { APP_NAME } from "@/config"
import { cachedRole, isLoggedIn } from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

export const Route = createFileRoute("/my-exports")({
  component: MyExportsPage,
  beforeLoad: () => {
    if (!isLoggedIn()) throw redirect({ to: "/login" })
    if (cachedRole() !== "student") throw redirect({ to: "/exports" })
  },
  head: () => ({
    meta: [{ title: `我的录音 / My Recordings - ${APP_NAME}` }],
  }),
})

function MyExportsPage() {
  const { t } = useI18n()
  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="mx-auto flex w-full max-w-3xl items-center justify-between gap-3 px-4 py-6 sm:px-6">
        <Logo />
        <div className="flex items-center gap-2">
          <LanguageToggle />
          <Link
            to="/join"
            className="inline-flex h-11 items-center rounded-md px-3 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            {t({ zh: "返回班级", en: "Back to classes" })}
          </Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 pb-16 sm:px-6">
        <h1 className="mb-4 text-2xl font-bold tracking-tight">
          {t({ zh: "我的录音", en: "My recordings" })}
        </h1>
        <ExportCenter mode="self" />
      </main>
    </div>
  )
}
