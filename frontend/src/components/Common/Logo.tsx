import { Link } from "@tanstack/react-router"
import { AudioLines } from "lucide-react"
import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content = (
    <span className={cn("inline-flex items-center gap-3", className)}>
      <span className="grid size-10 shrink-0 place-items-center rounded-2xl bg-primary text-primary-foreground">
        <AudioLines className="size-6" />
      </span>
      {variant !== "icon" && (
        <span
          className={cn(
            "text-left",
            variant === "responsive" && "group-data-[collapsible=icon]:hidden",
          )}
        >
          <span className="block text-xl font-bold tracking-tight">
            SpeakUp<span className="text-primary">.</span>
          </span>
          <span className="block whitespace-nowrap text-[10px] font-medium tracking-[0.1em] text-muted-foreground">
            开口说 · 英语口语课堂
          </span>
        </span>
      )}
    </span>
  )
  return asLink ? (
    <Link to="/" aria-label="SpeakUp 首页">
      {content}
    </Link>
  ) : (
    content
  )
}
