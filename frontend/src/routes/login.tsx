import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { ArrowRight, Presentation, UsersRound } from "lucide-react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"
import type { Body_login_login_access_token as AccessToken } from "@/client"
import { LoginService } from "@/client"
import { LoginLayout } from "@/components/Common/LoginLayout"
import { Button } from "@/components/ui/button"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { APP_NAME } from "@/config"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"
import useLoginOptions from "@/hooks/useLoginOptions"
import { extractErrorMessage } from "@/utils"

const formSchema = z.object({
  username: z
    .string()
    .trim()
    .pipe(z.email({ message: "请输入有效的邮箱地址" })),
  password: z.string().min(1, { message: "请输入密码" }),
}) satisfies z.ZodType<AccessToken>

const studentSchema = z.object({
  username: z.string().min(1, { message: "请输入学号" }),
  password: z.string().min(1, { message: "请输入密码" }),
})

type FormData = z.infer<typeof formSchema>

export const Route = createFileRoute("/login")({
  component: Login,
  beforeLoad: async () => {
    if (isLoggedIn()) throw redirect({ to: "/" })
  },
  head: () => ({ meta: [{ title: `登录 - ${APP_NAME}` }] }),
})

function StudentLogin() {
  const { loginMutation } = useAuth()
  const form = useForm<z.infer<typeof studentSchema>>({
    resolver: zodResolver(studentSchema),
    defaultValues: { username: "", password: "" },
  })
  return (
    <Form {...form}>
      <form
        className="space-y-4"
        onSubmit={form.handleSubmit((data) => {
          if (!loginMutation.isPending) loginMutation.mutate(data)
        })}
        noValidate
      >
        <p className="text-sm leading-6 text-muted-foreground">
          用老师发放的学号账号登录；默认密码
          brs123456，登录后可在侧边栏自行修改。
        </p>
        <FormField
          control={form.control}
          name="username"
          render={({ field }) => (
            <FormItem>
              <FormLabel>学号</FormLabel>
              <FormControl>
                <Input
                  {...field}
                  data-testid="student-no-input"
                  placeholder="请输入你的学号"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  className="h-12 rounded-xl bg-background/50 px-4 font-mono"
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
              <FormLabel>密码</FormLabel>
              <FormControl>
                <Input
                  {...field}
                  type="password"
                  data-testid="student-password-input"
                  placeholder="默认密码 brs123456 或你修改后的密码"
                  autoComplete="current-password"
                  className="h-12 rounded-xl bg-background/50 px-4"
                />
              </FormControl>
              <FormMessage className="text-xs" />
            </FormItem>
          )}
        />
        <LoadingButton
          type="submit"
          className="h-12 w-full rounded-xl"
          loading={loginMutation.isPending}
        >
          登录 <ArrowRight className="size-4" />
        </LoadingButton>
        <p className="text-xs text-muted-foreground">
          没有账号或忘记密码？请联系任课老师。
        </p>
      </form>
    </Form>
  )
}

function DemoEntry() {
  const demoMutation = useMutation({
    mutationFn: (_role: "teacher" | "admin") => LoginService.loginDemo(),
    onSuccess: (data, role) => {
      localStorage.setItem("access_token", data.access_token)
      window.location.href =
        role === "teacher" ? "/t/DEMO01" : "/admin/passages"
    },
    onError: () => toast.error("演示入口不可用，请使用账号登录"),
  })
  return (
    <details className="border-t pt-4 text-xs text-muted-foreground">
      <summary className="cursor-pointer rounded-sm focus-visible:outline-ring">
        本地演示体验（仅开发环境）
      </summary>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          asChild
          variant="outline"
          size="sm"
          disabled={demoMutation.isPending}
        >
          <RouterLink to="/j/$code" params={{ code: "DEMO01" }}>
            学生演示
          </RouterLink>
        </Button>
        {(["teacher", "admin"] as const).map((role) => (
          <Button
            key={role}
            type="button"
            variant="outline"
            size="sm"
            disabled={demoMutation.isPending}
            onClick={() => demoMutation.mutate(role)}
          >
            {demoMutation.isPending && demoMutation.variables === role
              ? "进入中…"
              : role === "teacher"
                ? "教师演示"
                : "管理员演示"}
          </Button>
        ))}
      </div>
    </details>
  )
}

function Login() {
  const { loginMutation } = useAuth()
  const options = useLoginOptions()
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    defaultValues: { username: "", password: "" },
  })
  const onSubmit = (data: FormData) => {
    if (!loginMutation.isPending) loginMutation.mutate(data)
  }

  return (
    <LoginLayout>
      <div className="space-y-5 sm:space-y-6">
        <div className="space-y-2">
          <p className="text-xs font-semibold tracking-[0.18em] text-primary">
            WELCOME TO SPEAKUP
          </p>
          <h2 className="text-2xl font-semibold sm:text-3xl">
            欢迎来到 SpeakUp
          </h2>
          <p className="text-sm text-muted-foreground">
            选择入口，开始今天的口语课堂。
          </p>
        </div>
        <Tabs defaultValue="account" className="gap-5">
          <TabsList className="grid h-11 w-full grid-cols-2">
            <TabsTrigger value="student">
              <UsersRound />
              学生登录
            </TabsTrigger>
            <TabsTrigger value="account">
              <Presentation />
              教师 / 管理员
            </TabsTrigger>
          </TabsList>
          <TabsContent value="student">
            <StudentLogin />
          </TabsContent>
          <TabsContent value="account">
            <Form {...form}>
              <form
                onSubmit={form.handleSubmit(onSubmit)}
                className="space-y-4"
                noValidate
              >
                <FormField
                  control={form.control}
                  name="username"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>邮箱地址</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          data-testid="email-input"
                          placeholder="请输入你的邮箱"
                          autoComplete="username"
                          autoCapitalize="none"
                          spellCheck={false}
                          className="h-12 rounded-xl bg-background/50 px-4"
                          type="email"
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
                      <div className="flex items-center justify-between gap-3">
                        <FormLabel>密码</FormLabel>
                        {options.data?.password_recovery_enabled && (
                          <RouterLink
                            to="/recover-password"
                            className="text-xs text-primary underline-offset-4 hover:underline"
                          >
                            忘记密码？
                          </RouterLink>
                        )}
                      </div>
                      <FormControl>
                        <PasswordInput
                          {...field}
                          data-testid="password-input"
                          placeholder="请输入密码"
                          autoComplete="current-password"
                          className="h-12 rounded-xl bg-background/50 px-4 pr-12"
                        />
                      </FormControl>
                      <FormMessage className="text-xs" />
                    </FormItem>
                  )}
                />
                {loginMutation.isError && (
                  <p role="alert" className="text-sm text-destructive">
                    {extractErrorMessage(loginMutation.error)}
                  </p>
                )}
                <LoadingButton
                  className="h-12 w-full rounded-xl text-sm"
                  type="submit"
                  loading={loginMutation.isPending}
                >
                  {loginMutation.isPending ? "正在登录…" : "登录工作台"}
                  {!loginMutation.isPending && (
                    <ArrowRight className="size-4" />
                  )}
                </LoadingButton>
              </form>
            </Form>
            {options.data && (
              <div className="mt-4 space-y-2 text-center text-xs leading-5 text-muted-foreground">
                {options.data.registration_enabled ? (
                  <p>
                    还没有账号？{" "}
                    <RouterLink
                      to="/signup"
                      className="font-semibold text-primary hover:underline"
                    >
                      注册账号
                    </RouterLink>
                  </p>
                ) : (
                  <p>教师与管理员账号由学校统一开通。</p>
                )}
                {!options.data.password_recovery_enabled && (
                  <p>忘记密码？请联系学校管理员重置。</p>
                )}
              </div>
            )}
          </TabsContent>
        </Tabs>
        {options.isError && (
          <p role="status" className="text-xs text-muted-foreground">
            入口信息暂未加载，仍可账号登录或输入课堂码。
            <button
              type="button"
              className="ml-1 text-primary underline"
              onClick={() => void options.refetch()}
            >
              重试
            </button>
          </p>
        )}
        {options.data?.demo_enabled && <DemoEntry />}
      </div>
    </LoginLayout>
  )
}
