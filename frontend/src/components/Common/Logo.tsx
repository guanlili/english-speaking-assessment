import { Link } from "@tanstack/react-router"
import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

// 替换成你自己的品牌 Logo，或者修改下方的文字/图标
export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const icon = (
    <span className={cn("font-bold text-lg leading-none", className)}>
      {variant === "icon" ? "A" : "My App"}
    </span>
  )

  if (!asLink) return icon
  return <Link to="/">{icon}</Link>
}
