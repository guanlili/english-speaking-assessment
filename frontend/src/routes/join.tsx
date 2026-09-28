import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { ArrowRight } from "lucide-react"
import { useEffect, useState } from "react"
import { Logo } from "@/components/Common/Logo"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { APP_NAME } from "@/config"
import { isStudentLoggedIn } from "@/hooks/useAuth"
import { lastJoinedCode } from "@/lib/classroom-student"

export const Route = createFileRoute("/join")({
  component: JoinHubPage,
  head: () => ({ meta: [{ title: `进入课堂 - ${APP_NAME}` }] }),
})

/** 学生登录后的落点：输入课堂码进入课堂（/j/$code 完成加入）。 */
function JoinHubPage() {
  const navigate = useNavigate()
  const [code, setCode] = useState("")

  useEffect(() => {
    if (!isStudentLoggedIn()) {
      void navigate({ to: "/login" })
      return
    }
    const last = lastJoinedCode()
    if (last) void navigate({ to: "/home/$code", params: { code: last } })
  }, [navigate])

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-7">
        <Logo asLink={false} />
      </header>
      <main className="mx-auto flex w-full max-w-md flex-1 items-center px-6">
        <Card className="w-full py-8 shadow-xl shadow-primary/5">
          <CardHeader>
            <CardTitle className="text-2xl">进入课堂</CardTitle>
            <CardDescription>输入老师给你的课堂码开始练习</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                const c = code.trim().toUpperCase()
                if (c) void navigate({ to: "/j/$code", params: { code: c } })
              }}
              className="space-y-5"
            >
              <Input
                className="h-12 text-center font-mono text-lg tracking-widest"
                placeholder="课堂码，如 DEMO01"
                maxLength={16}
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                aria-label="课堂码"
              />
              <LoadingButton type="submit" className="h-12 w-full">
                下一步 <ArrowRight className="size-4" />
              </LoadingButton>
            </form>
          </CardContent>
        </Card>
      </main>
    </div>
  )
}
