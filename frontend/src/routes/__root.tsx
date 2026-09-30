import { createRootRoute, HeadContent, Outlet } from "@tanstack/react-router"
import { lazy, Suspense } from "react"
import ErrorComponent from "@/components/Common/ErrorComponent"
import NotFound from "@/components/Common/NotFound"
import { useIsMobile } from "@/hooks/useMobile"
import { I18nProvider } from "@/lib/i18n"

const TanStackRouterDevtools = import.meta.env.PROD
  ? () => null
  : lazy(() =>
      import("@tanstack/react-router-devtools").then((r) => ({
        default: r.TanStackRouterDevtools,
      })),
    )

const ReactQueryDevtools = import.meta.env.PROD
  ? () => null
  : lazy(() =>
      import("@tanstack/react-query-devtools").then((r) => ({
        default: r.ReactQueryDevtools,
      })),
    )

function RootLayout() {
  const isMobile = useIsMobile()
  return (
    <I18nProvider>
      <HeadContent />
      <Outlet />
      {!isMobile && (
        <Suspense>
          <TanStackRouterDevtools position="bottom-right" />
          <ReactQueryDevtools initialIsOpen={false} />
        </Suspense>
      )}
    </I18nProvider>
  )
}

export const Route = createRootRoute({
  component: RootLayout,
  notFoundComponent: () => <NotFound />,
  errorComponent: () => <ErrorComponent />,
})
