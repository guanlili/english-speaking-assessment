import { Link } from "@tanstack/react-router"
import { SpellCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"

export function EmptyCard({
  code,
  title,
  body,
}: {
  code: string
  title: string
  body: string
}) {
  const { t } = useI18n()
  return (
    <Card className="items-center px-6 py-12 text-center">
      <SpellCheck className="size-10 text-primary" />
      <h1 className="mt-3 text-xl font-semibold">{title}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{body}</p>
      <Button asChild className="mt-4">
        <Link to="/vocab/$code/books" params={{ code }}>
          {t({ zh: "去词库挑词", en: "Browse Word Books" })}
        </Link>
      </Button>
    </Card>
  )
}
