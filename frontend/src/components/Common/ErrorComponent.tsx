import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { readStoredLang, resolveBi } from "@/lib/bi"

const ErrorComponent = () => {
  // Root errors can render outside I18nProvider.
  const lang = readStoredLang()
  return (
    <div
      className="flex min-h-screen items-center justify-center flex-col p-4"
      data-testid="error-component"
    >
      <div className="flex items-center z-10">
        <div className="flex flex-col ml-4 items-center justify-center p-4">
          <span className="text-6xl md:text-8xl font-bold leading-none mb-4">
            {resolveBi({ zh: "页面出错", en: "Error" }, lang)}
          </span>
        </div>
      </div>

      <p className="text-lg text-muted-foreground mb-4 text-center z-10">
        {resolveBi(
          {
            zh: "页面暂时无法显示，请重新加载或返回首页。",
            en: "This page could not be displayed. Reload it or return home.",
          },
          lang,
        )}
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Button type="button" onClick={() => window.location.reload()}>
          {resolveBi({ zh: "重新加载页面", en: "Reload Page" }, lang)}
        </Button>
        <Button asChild variant="outline">
          <Link to="/">
            {resolveBi({ zh: "返回首页", en: "Go Home" }, lang)}
          </Link>
        </Button>
      </div>
    </div>
  )
}

export default ErrorComponent
