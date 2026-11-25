import { Languages } from "lucide-react"
import { type Lang, useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"

const CHOICES: { value: Lang; label: string }[] = [
  { value: "zh", label: "中" },
  { value: "en", label: "EN" },
]

/** 中/EN 切换（全站双语准则的入口，放在认证页头部与各端导航）。 */
export function LanguageToggle({ className }: { className?: string }) {
  const { lang, setLang } = useI18n()
  return (
    <fieldset
      aria-label="语言 / Language"
      className={cn(
        "inline-flex h-12 items-center rounded-full border border-border bg-card p-0.5 text-xs font-medium sm:h-8",
        className,
      )}
    >
      <Languages
        className="mx-1.5 hidden size-3.5 text-muted-foreground sm:inline-block"
        aria-hidden="true"
      />
      {CHOICES.map((choice) => (
        <button
          key={choice.value}
          type="button"
          aria-pressed={lang === choice.value}
          onClick={() => setLang(choice.value)}
          className={cn(
            "h-11 min-w-11 rounded-full px-2 transition-colors hover:text-foreground sm:h-7 sm:min-w-9",
            lang === choice.value
              ? "bg-foreground text-background"
              : "text-muted-foreground",
          )}
        >
          {choice.label}
        </button>
      ))}
    </fieldset>
  )
}

export default LanguageToggle
