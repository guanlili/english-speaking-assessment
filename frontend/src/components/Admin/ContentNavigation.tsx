import { Link } from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"

export function ContentNavigation() {
  return (
    <Link
      to="/create"
      search={{ kind: "reading" }}
      className="inline-flex items-center gap-2 text-sm text-primary"
    >
      <ArrowLeft className="size-4" />
      返回题目库
    </Link>
  )
}
