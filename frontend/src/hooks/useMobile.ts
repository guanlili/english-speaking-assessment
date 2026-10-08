import * as React from "react"

/**
 * JS 侧移动判定断点 = 768，刻意与 Tailwind `md:`（768px）对齐：
 * StudentShell 的手机底栏/桌面侧栏用 `md:hidden` / `md:flex` 切换，
 * ui/sidebar（shadcn）也用本 hook 在同一宽度切移动抽屉——JS 与 CSS
 * 必须同宽切换才不会出现「底栏和抽屉同时出现」的中间态。
 * 390/820/1180 是 e2e 的设备视口宽（responsive.spec.ts），不是设计
 * 断点；把这里改成 820 会与 md: 脱钩，勿改。
 */
const MOBILE_BREAKPOINT = 768

export function useIsMobile() {
  const [isMobile, setIsMobile] = React.useState<boolean | undefined>(undefined)

  React.useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const onChange = () => {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    }
    mql.addEventListener("change", onChange)
    setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    return () => mql.removeEventListener("change", onChange)
  }, [])

  return !!isMobile
}
