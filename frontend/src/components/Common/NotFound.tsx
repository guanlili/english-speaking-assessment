import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { readStoredLang, resolveBi } from "@/lib/bi"

const NotFound = () => {
  const lang = readStoredLang()
  return (
    <div
      className="flex min-h-screen items-center justify-center flex-col p-4"
      data-testid="not-found"
    >
      <div className="flex items-center z-10">
        <div className="flex flex-col ml-4 items-center justify-center p-4">
          <span className="text-6xl md:text-8xl font-bold leading-none mb-4">
            404
          </span>
          <span className="text-2xl font-bold mb-2">
            {resolveBi({ zh: "页面不存在", en: "Page not found" }, lang)}
          </span>
        </div>
      </div>

      <p className="text-lg text-muted-foreground mb-4 text-center z-10">
        {resolveBi(
          {
            zh: "没有找到这个页面，请检查地址或返回首页。",
            en: "This page could not be found. Check the address or return home.",
          },
          lang,
        )}
      </p>
      <div className="z-10">
        <Button className="mt-4" asChild>
          <Link to="/">
            {resolveBi({ zh: "返回首页", en: "Go Home" }, lang)}
          </Link>
        </Button>
      </div>
    </div>
  )
}

export default NotFound
