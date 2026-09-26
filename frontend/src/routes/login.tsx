import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
  useNavigate,
} from "@tanstack/react-router"
import { BookOpen, Presentation, UsersRound } from "lucide-react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"
import type { Body_login_login_access_token as AccessToken } from "@/client"
import { LoginService } from "@/client"
import { AuthLayout } from "@/components/Common/AuthLayout"
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
  username: z.email(),
  password: z
    .string()
    .min(1, { message: "Password is required" })
    .min(8, { message: "Password must be at least 8 characters" }),
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
        title: `Log In - ${APP_NAME}`,
      },
    ],
  }),
})

const DEMO_CLASSROOM = "DEMO01"

function RoleCards({ navigate }: { navigate: (to: string) => void }) {
  const demoMutation = useMutation({
    mutationFn: () => LoginService.loginDemo(),
    onSuccess: (data) => {
      localStorage.setItem("access_token", data.access_token ?? "")
      window.location.href = "/admin/passages"
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
      desc: "课堂码进入，开始练习",
      icon: UsersRound,
      onClick: () => navigate(`/j/${DEMO_CLASSROOM}`),
    },
    {
      key: "teacher",
      label: "教师",
      desc: "课堂面板与今日指派",
      icon: Presentation,
      onClick: () => navigate(`/t/${DEMO_CLASSROOM}`),
    },
    {
      key: "admin",
      label: "管理员",
      desc: "内容与词表管理",
      icon: BookOpen,
      onClick: () => demoMutation.mutate(),
    },
  ]

  return (
    <div className="mb-2 grid grid-cols-3 gap-2">
      {roles.map((role) => (
        <button
          key={role.key}
          type="button"
          onClick={role.onClick}
          disabled={demoMutation.isPending && role.key === "admin"}
          className="flex flex-col items-center gap-1.5 rounded-xl border border-border bg-card px-2 py-3.5 text-center transition hover:border-primary/50 hover:shadow-md"
        >
          <span className="flex size-9 items-center justify-center rounded-xl bg-secondary text-primary">
            <role.icon className="size-4.5" />
          </span>
          <span className="text-xs font-semibold">{role.label}</span>
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
    <AuthLayout>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex flex-col gap-6"
        >
          <div className="flex flex-col items-center gap-1.5 text-center">
            <h1 className="text-2xl font-bold">Login to your account</h1>
            <p className="text-xs text-muted-foreground">
              演示环境：点击角色直接进入对应视角
            </p>
          </div>

          <RoleCards navigate={(to) => void navigate({ to })} />

          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            或使用账号密码
            <span className="h-px flex-1 bg-border" />
          </div>

          <div className="grid gap-4">
            <FormField
              control={form.control}
              name="username"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input
                      data-testid="email-input"
                      placeholder="user@example.com"
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
                    <FormLabel>Password</FormLabel>
                    <RouterLink
                      to="/recover-password"
                      className="ml-auto text-sm underline-offset-4 hover:underline"
                    >
                      Forgot your password?
                    </RouterLink>
                  </div>
                  <FormControl>
                    <PasswordInput
                      data-testid="password-input"
                      placeholder="Password"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />

            <LoadingButton type="submit" loading={loginMutation.isPending}>
              Log In
            </LoadingButton>
          </div>

          <div className="text-center text-sm">
            Don't have an account yet?{" "}
            <RouterLink to="/signup" className="underline underline-offset-4">
              Sign up
            </RouterLink>
          </div>
        </form>
      </Form>
    </AuthLayout>
  )
}
