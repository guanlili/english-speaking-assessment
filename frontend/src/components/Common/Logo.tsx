import { Link } from "@tanstack/react-router"
import { AudioLines } from "lucide-react"
import { useI18n } from "@/lib/i18n"
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
  const { t } = useI18n()
  const content = (
    <span className={cn("inline-flex items-center gap-3", className)}>
      <span className="grid size-10 shrink-0 place-items-center rounded-2xl bg-primary text-primary-foreground">
        <AudioLines className="size-6" aria-hidden="true" />
      </span>
      {variant !== "icon" && (
        <span
          className={cn(
            "text-left",
            variant === "responsive" && "group-data-[collapsible=icon]:hidden",
          )}
        >
          <span className="block text-xl font-bold tracking-tight">
            BELP<span className="text-primary">.</span>
          </span>
          {/* 副标题走双语：外教把界面切到英文后，Logo 下仍出现中文会很突兀 */}
          <span className="block whitespace-nowrap text-[10px] font-medium tracking-[0.1em] text-muted-foreground">
            {t({
              zh: "开口说 · 英语口语课堂",
              en: "Speak up · Spoken English Class",
            })}
          </span>
        </span>
      )}
    </span>
  )
  return asLink ? (
    <Link to="/" aria-label={t({ zh: "BELP 首页", en: "BELP home" })}>
      {content}
    </Link>
  ) : (
    content
  )
}
