import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
  useNavigate,
} from "@tanstack/react-router"
import { ArrowRight, BookOpen, Presentation, UsersRound } from "lucide-react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"
import type { Body_login_login_access_token as AccessToken } from "@/client"
import { LoginService } from "@/client"
import { LoginLayout } from "@/components/Common/LoginLayout"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { PasswordInput } from "@/components/ui/password-input"
import { APP_NAME } from "@/config"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"

const formSchema = z.object({
  username: z.email({ message: "请输入有效的邮箱地址" }),
  password: z
    .string()
    .min(1, { message: "请输入密码" })
    .min(8, { message: "密码至少需要 8 个字符" }),
}) satisfies z.ZodType<AccessToken>

type FormData = z.infer<typeof formSchema>

export const Route = createFileRoute("/login")({
  component: Login,
  beforeLoad: async () => {
    if (isLoggedIn()) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: `登录 - ${APP_NAME}`,
      },
    ],
  }),
})

const DEMO_CLASSROOM = "DEMO01"

function RoleCards({ navigate }: { navigate: (to: string) => void }) {
  const demoMutation = useMutation({
    mutationFn: (_role: "teacher" | "admin") => LoginService.loginDemo(),
    onSuccess: (data, role) => {
      localStorage.setItem("access_token", data.access_token ?? "")
      window.location.href =
        role === "teacher" ? `/t/${DEMO_CLASSROOM}` : "/admin/passages"
    },
    onError: () => {
      toast.error("演示登录不可用", {
        description: "该入口仅在本地演示环境开放，请使用下方账号密码登录",
      })
    },
  })

  const roles = [
    {
      key: "student",
      label: "学生",
      desc: "进入课堂练习",
      icon: UsersRound,
      onClick: () => navigate(`/j/${DEMO_CLASSROOM}`),
    },
    {
      key: "teacher",
      label: "教师",
      desc: "查看课堂面板",
      icon: Presentation,
      onClick: () => demoMutation.mutate("teacher"),
    },
    {
      key: "admin",
      label: "管理员",
      desc: "管理教学内容",
      icon: BookOpen,
      onClick: () => demoMutation.mutate("admin"),
    },
  ]

  return (
    <div className="grid grid-cols-3 gap-2.5">
      {roles.map((role) => (
        <button
          key={role.key}
          type="button"
          onClick={role.onClick}
          disabled={demoMutation.isPending}
          className="group flex flex-col items-center gap-2 rounded-2xl border border-border bg-background/50 px-2 py-4 text-center transition duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-secondary/40 hover:shadow-sm disabled:pointer-events-none disabled:opacity-50"
        >
          <span className="flex size-10 items-center justify-center rounded-xl bg-secondary text-secondary-foreground transition group-hover:bg-primary group-hover:text-primary-foreground">
            <role.icon className="size-4.5" />
          </span>
          <span className="text-xs font-semibold">
            {demoMutation.isPending && role.key === demoMutation.variables
              ? "进入中…"
              : role.label}
          </span>
          <span className="text-[10px] leading-tight text-muted-foreground">
            {role.desc}
          </span>
        </button>
      ))}
    </div>
  )
}

function Login() {
  const { loginMutation } = useAuth()
  const navigate = useNavigate()
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      username: "",
      password: "",
    },
  })

  const onSubmit = (data: FormData) => {
    if (loginMutation.isPending) return
    loginMutation.mutate(data)
  }

  return (
    <LoginLayout>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex flex-col gap-6"
        >
          <div className="flex flex-col gap-2">
            <p className="mb-1 text-[10px] font-semibold tracking-[0.22em] text-primary">
              WELCOME BACK
            </p>
            <h2 className="text-2xl font-semibold sm:text-3xl">
              欢迎回到 SpeakUp
            </h2>
            <p className="text-xs text-muted-foreground">
              准备好了吗？开启今天的表达之旅。
            </p>
          </div>

          <div className="grid gap-3">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium">选择你的角色</span>
              <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] text-accent-foreground">
                演示体验 · 免登录
              </span>
            </div>
            <RoleCards navigate={(to) => void navigate({ to })} />
          </div>

          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            账号密码登录
            <span className="h-px flex-1 bg-border" />
          </div>

          <div className="grid gap-4">
            <FormField
              control={form.control}
              name="username"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>邮箱地址</FormLabel>
                  <FormControl>
                    <Input
                      data-testid="email-input"
                      placeholder="请输入你的邮箱"
                      autoComplete="username"
                      className="h-12 rounded-xl bg-background/50 px-4"
                      type="email"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <div className="flex items-center">
                    <FormLabel>密码</FormLabel>
                    <RouterLink
                      to="/recover-password"
                      className="ml-auto text-xs text-primary underline-offset-4 hover:underline"
                    >
                      忘记密码？
                    </RouterLink>
                  </div>
                  <FormControl>
                    <PasswordInput
                      data-testid="password-input"
                      placeholder="请输入密码"
                      autoComplete="current-password"
                      className="h-12 rounded-xl bg-background/50 px-4 pr-12"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />

            <LoadingButton
              className="mt-1 h-12 rounded-xl text-sm shadow-lg shadow-primary/10"
              type="submit"
              loading={loginMutation.isPending}
            >
              {loginMutation.isPending ? "正在登录…" : "登录工作台"}
              {!loginMutation.isPending && <ArrowRight className="size-4" />}
            </LoadingButton>
          </div>

          <div className="text-center text-xs text-muted-foreground">
            还没有账号？{" "}
            <RouterLink
              to="/signup"
              className="font-semibold text-primary underline-offset-4 hover:underline"
            >
              注册账号
            </RouterLink>
          </div>
        </form>
      </Form>
    </LoginLayout>
  )
}
