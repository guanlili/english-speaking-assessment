import { useMutation } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { KeyRound } from "lucide-react"
import { useState } from "react"
import { UsersService } from "@/client"
import { Logo } from "@/components/Common/Logo"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { APP_NAME } from "@/config"
import { isLoggedIn } from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { lastJoinedCode } from "@/lib/classroom-student"

export const Route = createFileRoute("/change-password")({
  component: ChangePasswordPage,
  head: () => ({ meta: [{ title: `修改密码 - ${APP_NAME}` }] }),
})

/** 首次登录（初始密码）强制改密；改完回到学生流程。 */
function ChangePasswordPage() {
  const navigate = useNavigate()
  const { showSuccessToast } = useCustomToast()
  const [current, setCurrent] = useState("")
  const [next, setNext] = useState("")
  const [confirm, setConfirm] = useState("")
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () =>
      UsersService.updatePasswordMe({
        requestBody: { current_password: current, new_password: next },
      }),
    onSuccess: () => {
      localStorage.setItem("esa:must-change-pw", "0")
      showSuccessToast("密码已修改")
      const code = lastJoinedCode()
      void navigate({
        to: code ? "/home/$code" : "/join",
        params: code ? { code } : undefined,
      })
    },
    onError: (err: { body?: { detail?: string } }) =>
      setError(err.body?.detail ?? "修改失败，请重试"),
  })

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (next.length < 8) {
      setError("新密码至少 8 位")
      return
    }
    if (next !== confirm) {
      setError("两次输入的新密码不一致")
      return
    }
    mutation.mutate()
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-7">
        <Logo asLink={false} />
      </header>
      <main className="mx-auto flex w-full max-w-md flex-1 items-center px-6">
        <Card className="w-full py-8 shadow-xl shadow-primary/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-2xl">
              <KeyRound className="size-5 text-primary" />
              修改密码
            </CardTitle>
            <CardDescription>
              当前密码是默认密码或你上次设置的密码；改成只有你知道的密码
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} className="space-y-4">
              <div className="space-y-2">
                <label htmlFor="cur-pw" className="text-sm font-medium">
                  当前密码（默认密码 brs123456）
                </label>
                <Input
                  id="cur-pw"
                  type="password"
                  autoComplete="current-password"
                  value={current}
                  onChange={(e) => setCurrent(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <label htmlFor="new-pw" className="text-sm font-medium">
                  新密码（至少 8 位）
                </label>
                <Input
                  id="new-pw"
                  type="password"
                  autoComplete="new-password"
                  value={next}
                  onChange={(e) => setNext(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <label htmlFor="confirm-pw" className="text-sm font-medium">
                  确认新密码
                </label>
                <Input
                  id="confirm-pw"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button
                type="submit"
                className="h-12 w-full"
                disabled={mutation.isPending}
              >
                {mutation.isPending ? "提交中…" : "保存"}
              </Button>
            </form>
            {isLoggedIn() && (
              <button
                type="button"
                className="mt-4 w-full text-center text-xs text-muted-underline text-muted-foreground hover:underline"
                onClick={() => void navigate({ to: "/login" })}
              >
                返回登录
              </button>
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  )
}
