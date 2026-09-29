import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { AlertCircle, ArrowRight, Presentation, UsersRound } from "lucide-react"
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
  FormDescription,
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
type LoginMutation = ReturnType<typeof useAuth>["loginMutation"]

const inputClassName =
  "h-12 rounded-lg border-[#233e34]/20 bg-[#f8f7f2] px-4 shadow-none placeholder:text-muted-foreground/75 focus-visible:bg-white dark:border-input dark:bg-background/50 dark:focus-visible:bg-background"
const submitClassName =
  "group h-12 w-full rounded-lg bg-[#204f40] text-sm font-semibold text-[#fffaf0] shadow-none hover:bg-[#173f32] focus-visible:ring-[#204f40]/30 dark:bg-[#efbd94] dark:text-[#193f33] dark:hover:bg-[#f4cca9] dark:focus-visible:ring-[#efbd94]/40"
const tabClassName =
  "h-11 gap-2 rounded-lg text-xs text-muted-foreground hover:text-foreground data-[state=active]:border-[#204f40] data-[state=active]:bg-[#204f40] data-[state=active]:text-[#fffaf0] data-[state=active]:shadow-none sm:text-sm dark:data-[state=active]:border-[#efbd94] dark:data-[state=active]:bg-[#efbd94] dark:data-[state=active]:text-[#193f33]"
const linkClassName =
  "rounded-sm font-semibold text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"

export const Route = createFileRoute("/login")({
  component: Login,
  beforeLoad: async () => {
    if (isLoggedIn()) throw redirect({ to: "/" })
  },
  head: () => ({ meta: [{ title: `登录 - ${APP_NAME}` }] }),
})

function LoginError({ error }: { error: unknown }) {
  return (
    <div
      role="alert"
      aria-atomic="true"
      className="flex items-start gap-2.5 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-3 text-sm leading-6 text-destructive"
    >
      <AlertCircle className="mt-1 size-4 shrink-0" aria-hidden="true" />
      <p>{extractErrorMessage(error)}</p>
    </div>
  )
}

function StudentLogin({ loginMutation }: { loginMutation: LoginMutation }) {
  const form = useForm<z.infer<typeof studentSchema>>({
    resolver: zodResolver(studentSchema),
    mode: "onBlur",
    defaultValues: { username: "", password: "" },
  })
  return (
    <Form {...form}>
      <form
        className="space-y-5"
        aria-label="学生登录"
        aria-describedby="student-login-description"
        aria-busy={loginMutation.isPending}
        onChange={() => {
          if (loginMutation.isError) loginMutation.reset()
        }}
        onSubmit={form.handleSubmit((data) => {
          if (!loginMutation.isPending) loginMutation.mutate(data)
        })}
        noValidate
      >
        <p
          id="student-login-description"
          className="text-sm leading-6 text-muted-foreground"
        >
          使用老师发放的学号账号，继续今日练习。
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
                  required
                  readOnly={loginMutation.isPending}
                  className={inputClassName}
                />
              </FormControl>
              <FormDescription className="sr-only">
                使用老师发放的学号。
              </FormDescription>
              <FormMessage role="alert" className="text-xs leading-5" />
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
                <PasswordInput
                  {...field}
                  data-testid="student-password-input"
                  placeholder="请输入密码"
                  autoComplete="current-password"
                  required
                  readOnly={loginMutation.isPending}
                  className={`${inputClassName} pr-12`}
                />
              </FormControl>
              <FormDescription className="text-xs leading-5">
                初始密码{" "}
                <code className="rounded bg-[#eee9dd] px-1 py-0.5 text-foreground dark:bg-muted">
                  brs123456
                </code>
                ，首次登录后请按提示修改。
              </FormDescription>
              <FormMessage role="alert" className="text-xs leading-5" />
            </FormItem>
          )}
        />
        {loginMutation.isError && <LoginError error={loginMutation.error} />}
        <LoadingButton
          type="submit"
          className={submitClassName}
          loading={loginMutation.isPending}
          aria-busy={loginMutation.isPending}
        >
          {loginMutation.isPending ? "正在登录…" : "登录，开始练习"}
          {!loginMutation.isPending && (
            <ArrowRight
              className="size-4 motion-safe:transition-transform motion-safe:group-hover:translate-x-1"
              aria-hidden="true"
            />
          )}
        </LoadingButton>
        <p className="text-center text-xs leading-5 text-muted-foreground">
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
    <details className="border-t border-[#233e34]/10 pt-4 text-xs text-muted-foreground dark:border-border">
      <summary className="cursor-pointer rounded-sm py-1.5 transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">
        本地演示体验（仅开发环境）
      </summary>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm" className="h-9 rounded-lg">
          <RouterLink
            to="/j/$code"
            params={{ code: "DEMO01" }}
            aria-disabled={demoMutation.isPending}
            tabIndex={demoMutation.isPending ? -1 : undefined}
            className="aria-disabled:pointer-events-none aria-disabled:opacity-50"
            onClick={(event) => {
              if (demoMutation.isPending) event.preventDefault()
            }}
          >
            学生演示
          </RouterLink>
        </Button>
        {(["teacher", "admin"] as const).map((role) => (
          <Button
            key={role}
            type="button"
            variant="outline"
            size="sm"
            className="h-9 rounded-lg"
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
      <p role="status" aria-atomic="true" className="sr-only">
        {demoMutation.isPending ? "正在进入演示，请稍候。" : ""}
      </p>
      {demoMutation.isError && (
        <p role="alert" className="mt-3 leading-5 text-destructive">
          演示入口不可用，请使用账号登录。
        </p>
      )}
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
      <div className="space-y-6">
        <div>
          <p
            className="mb-3 text-[10px] font-semibold tracking-[0.2em] text-muted-foreground"
            lang="en"
          >
            YOUR CLASSROOM AWAITS
          </p>
          <h2 className="text-2xl font-semibold tracking-tight sm:text-[28px]">
            欢迎来到 SpeakUp
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            选择你的身份，开始今天的口语课堂。
          </p>
        </div>
        <Tabs
          defaultValue="account"
          className="gap-6"
          onValueChange={() => loginMutation.reset()}
        >
          <TabsList
            aria-label="选择登录身份"
            className="grid h-auto w-full grid-cols-2 gap-1 rounded-xl border border-[#233e34]/10 bg-[#f0eee6] p-1.5 dark:border-border dark:bg-background/60"
          >
            <TabsTrigger
              value="student"
              className={tabClassName}
              disabled={loginMutation.isPending}
            >
              <UsersRound aria-hidden="true" />
              学生登录
            </TabsTrigger>
            <TabsTrigger
              value="account"
              className={tabClassName}
              disabled={loginMutation.isPending}
            >
              <Presentation aria-hidden="true" />
              教师 / 管理员
            </TabsTrigger>
          </TabsList>
          <TabsContent value="student">
            <StudentLogin loginMutation={loginMutation} />
          </TabsContent>
          <TabsContent value="account">
            <Form {...form}>
              <form
                aria-label="教师与管理员登录"
                aria-busy={loginMutation.isPending}
                onChange={() => {
                  if (loginMutation.isError) loginMutation.reset()
                }}
                onSubmit={form.handleSubmit(onSubmit)}
                className="space-y-5"
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
                          className={inputClassName}
                          type="email"
                          required
                          readOnly={loginMutation.isPending}
                        />
                      </FormControl>
                      <FormDescription className="sr-only">
                        请输入账号使用的邮箱地址。
                      </FormDescription>
                      <FormMessage role="alert" className="text-xs leading-5" />
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
                            className={`text-xs ${linkClassName}`}
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
                          className={`${inputClassName} pr-12`}
                          required
                          readOnly={loginMutation.isPending}
                        />
                      </FormControl>
                      <FormDescription className="sr-only">
                        请输入账号密码。
                      </FormDescription>
                      <FormMessage role="alert" className="text-xs leading-5" />
                    </FormItem>
                  )}
                />
                {loginMutation.isError && (
                  <LoginError error={loginMutation.error} />
                )}
                <LoadingButton
                  className={submitClassName}
                  type="submit"
                  loading={loginMutation.isPending}
                  aria-busy={loginMutation.isPending}
                >
                  {loginMutation.isPending ? "正在登录…" : "登录工作台"}
                  {!loginMutation.isPending && (
                    <ArrowRight
                      className="size-4 motion-safe:transition-transform motion-safe:group-hover:translate-x-1"
                      aria-hidden="true"
                    />
                  )}
                </LoadingButton>
              </form>
            </Form>
            {options.data && (
              <div className="mt-5 space-y-1.5 text-center text-xs leading-5 text-muted-foreground">
                {options.data.registration_enabled ? (
                  <p>
                    还没有账号？{" "}
                    <RouterLink to="/signup" className={linkClassName}>
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
        <p role="status" aria-atomic="true" className="sr-only">
          {loginMutation.isPending ? "正在验证账号，请稍候。" : ""}
        </p>
        {options.isError && (
          <p
            role="status"
            className="rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-xs leading-5 text-muted-foreground"
          >
            入口信息暂未加载，仍可使用学号或邮箱登录。
            <button
              type="button"
              className={`ml-1 disabled:opacity-50 ${linkClassName}`}
              disabled={options.isFetching}
              onClick={() => void options.refetch()}
            >
              {options.isFetching ? "重试中…" : "重试"}
            </button>
          </p>
        )}
        {options.data?.demo_enabled && <DemoEntry />}
      </div>
    </LoginLayout>
  )
}
