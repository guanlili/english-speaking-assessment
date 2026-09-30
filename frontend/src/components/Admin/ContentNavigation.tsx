import { Link } from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"
import { useI18n } from "@/lib/i18n"

export function ContentNavigation() {
  const { t } = useI18n()
  return (
    <Link
      to="/create"
      search={{ kind: "reading" }}
      className="inline-flex items-center gap-2 text-sm text-primary"
    >
      <ArrowLeft className="size-4" />
      {t({ zh: "返回题目库", en: "Back to Question Bank" })}
    </Link>
  )
}
