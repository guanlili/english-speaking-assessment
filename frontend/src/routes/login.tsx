import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { AlertCircle, ArrowRight, Presentation, UsersRound } from "lucide-react"
import { useMemo } from "react"
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
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"

type FormData = z.infer<ReturnType<typeof buildAccountSchema>>
type LoginMutation = ReturnType<typeof useAuth>["loginMutation"]

// 校验消息随语言切换：schema 在组件内按当前语言重建
function buildAccountSchema(t: ReturnType<typeof useI18n>["t"]) {
  return z.object({
    username: z
      .string()
      .trim()
      .pipe(
        z.email({
          message: t({
            zh: "请输入有效的邮箱地址",
            en: "Enter a valid email address",
          }),
        }),
      ),
    password: z
      .string()
      .min(1, { message: t({ zh: "请输入密码", en: "Enter your password" }) }),
  }) satisfies z.ZodType<AccessToken>
}

function buildStudentSchema(t: ReturnType<typeof useI18n>["t"]) {
  return z.object({
    username: z.string().min(1, {
      message: t({ zh: "请输入学号", en: "Enter your student ID" }),
    }),
    password: z
      .string()
      .min(1, { message: t({ zh: "请输入密码", en: "Enter your password" }) }),
  })
}

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
  head: () => ({ meta: [{ title: `登录 / Sign in - ${APP_NAME}` }] }),
})

function LoginError({ error }: { error: unknown }) {
  const { t } = useI18n()
  const detail = extractErrorMessage(error)
  // 后端 detail 是中文稳定文案；英文环境映射常见错误，其余给通用提示
  const message = detail.includes("账号或密码不正确")
    ? t({ zh: detail, en: "Incorrect account or password" })
    : detail.includes("暂时不可用") || detail.includes("网络连接")
      ? t({
          zh: detail,
          en: "Service temporarily unavailable, please try again",
        })
      : t({ zh: detail, en: "Sign-in failed, please try again" })
  return (
    <div
      role="alert"
      aria-atomic="true"
      className="flex items-start gap-2.5 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-3 text-sm leading-6 text-destructive"
    >
      <AlertCircle className="mt-1 size-4 shrink-0" aria-hidden="true" />
      <p>{message}</p>
    </div>
  )
}

function StudentLogin({ loginMutation }: { loginMutation: LoginMutation }) {
  const { t } = useI18n()
  const schema = useMemo(() => buildStudentSchema(t), [t])
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    mode: "onBlur",
    defaultValues: { username: "", password: "" },
  })
  return (
    <Form {...form}>
      <form
        className="space-y-5"
        aria-label={t({ zh: "学生登录", en: "Student sign-in" })}
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
          {t({
            zh: "使用老师发放的学号账号，继续今日练习。",
            en: "Sign in with the student ID from your teacher to continue today's practice.",
          })}
        </p>
        <FormField
          control={form.control}
          name="username"
          render={({ field }) => (
            <FormItem>
              <FormLabel>{t({ zh: "学号", en: "Student ID" })}</FormLabel>
              <FormControl>
                <Input
                  {...field}
                  data-testid="student-no-input"
                  placeholder={t({
                    zh: "请输入你的学号",
                    en: "Enter your student ID",
                  })}
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  required
                  readOnly={loginMutation.isPending}
                  className={inputClassName}
                />
              </FormControl>
              <FormDescription className="sr-only">
                {t({
                  zh: "使用老师发放的学号。",
                  en: "Use the student ID issued by your teacher.",
                })}
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
              <FormLabel>{t({ zh: "密码", en: "Password" })}</FormLabel>
              <FormControl>
                <PasswordInput
                  {...field}
                  data-testid="student-password-input"
                  placeholder={t({
                    zh: "请输入密码",
                    en: "Enter your password",
                  })}
                  autoComplete="current-password"
                  required
                  readOnly={loginMutation.isPending}
                  className={`${inputClassName} pr-12`}
                />
              </FormControl>
              <FormDescription className="text-xs leading-5">
                {t({ zh: "初始密码", en: "Default password" })}{" "}
                <code className="rounded bg-[#eee9dd] px-1 py-0.5 text-foreground dark:bg-muted">
                  brs123456
                </code>
                {t({
                  zh: "，首次登录后请按提示修改。",
                  en: " — change it after your first sign-in.",
                })}
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
          {loginMutation.isPending
            ? t({ zh: "正在登录…", en: "Signing in…" })
            : t({ zh: "登录，开始练习", en: "Sign in & practice" })}
          {!loginMutation.isPending && (
            <ArrowRight
              className="size-4 motion-safe:transition-transform motion-safe:group-hover:translate-x-1"
              aria-hidden="true"
            />
          )}
        </LoadingButton>
        <p className="text-center text-xs leading-5 text-muted-foreground">
          {t({
            zh: "没有账号或忘记密码？请联系任课老师。",
            en: "No account or forgot your password? Please contact your teacher.",
          })}
        </p>
      </form>
    </Form>
  )
}

function DemoEntry() {
  const { t } = useI18n()
  const demoMutation = useMutation({
    mutationFn: (_role: "teacher" | "admin") => LoginService.loginDemo(),
    onSuccess: (data, role) => {
      localStorage.setItem("access_token", data.access_token)
      window.location.href =
        role === "teacher" ? "/t/DEMO01" : "/admin/passages"
    },
    onError: () =>
      toast.error(
        t({
          zh: "演示入口不可用，请使用账号登录",
          en: "Demo sign-in unavailable, please use your account",
        }),
      ),
  })
  return (
    <details className="border-t border-[#233e34]/10 pt-4 text-xs text-muted-foreground dark:border-border">
      <summary className="cursor-pointer rounded-sm py-1.5 transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">
        {t({ zh: "本地演示体验（仅开发环境）", en: "Local demo (dev only)" })}
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
            {t({ zh: "学生演示", en: "Student demo" })}
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
              ? t({ zh: "进入中…", en: "Entering…" })
              : role === "teacher"
                ? t({ zh: "教师演示", en: "Teacher demo" })
                : t({ zh: "管理员演示", en: "Admin demo" })}
          </Button>
        ))}
      </div>
      <p role="status" aria-atomic="true" className="sr-only">
        {demoMutation.isPending
          ? t({
              zh: "正在进入演示，请稍候。",
              en: "Entering demo, please wait.",
            })
          : ""}
      </p>
      {demoMutation.isError && (
        <p role="alert" className="mt-3 leading-5 text-destructive">
          {t({
            zh: "演示入口不可用，请使用账号登录。",
            en: "Demo sign-in unavailable, please use your account.",
          })}
        </p>
      )}
    </details>
  )
}

function Login() {
  const { t } = useI18n()
  const { loginMutation } = useAuth()
  const options = useLoginOptions()
  const schema = useMemo(() => buildAccountSchema(t), [t])
  const form = useForm<FormData>({
    resolver: zodResolver(schema),
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
            {t({ zh: "欢迎来到 SpeakUp", en: "Welcome to SpeakUp" })}
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {t({
              zh: "选择你的身份，开始今天的口语课堂。",
              en: "Choose your role and start today's speaking class.",
            })}
          </p>
        </div>
        <Tabs
          defaultValue="account"
          className="gap-6"
          onValueChange={() => loginMutation.reset()}
        >
          <TabsList
            aria-label={t({ zh: "选择登录身份", en: "Choose your role" })}
            className="grid h-auto w-full grid-cols-2 gap-1 rounded-xl border border-[#233e34]/10 bg-[#f0eee6] p-1.5 dark:border-border dark:bg-background/60"
          >
            <TabsTrigger
              value="student"
              className={tabClassName}
              disabled={loginMutation.isPending}
            >
              <UsersRound aria-hidden="true" />
              {t({ zh: "学生登录", en: "Student" })}
            </TabsTrigger>
            <TabsTrigger
              value="account"
              className={tabClassName}
              disabled={loginMutation.isPending}
            >
              <Presentation aria-hidden="true" />
              {t({ zh: "教师 / 管理员", en: "Teacher / Admin" })}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="student">
            <StudentLogin loginMutation={loginMutation} />
          </TabsContent>
          <TabsContent value="account">
            <Form {...form}>
              <form
                aria-label={t({
                  zh: "教师与管理员登录",
                  en: "Teacher and admin sign-in",
                })}
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
                      <FormLabel>
                        {t({ zh: "邮箱地址", en: "Email" })}
                      </FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          data-testid="email-input"
                          placeholder={t({
                            zh: "请输入你的邮箱",
                            en: "Enter your email",
                          })}
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
                        {t({
                          zh: "请输入账号使用的邮箱地址。",
                          en: "Enter the email address of your account.",
                        })}
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
                        <FormLabel>
                          {t({ zh: "密码", en: "Password" })}
                        </FormLabel>
                        {options.data?.password_recovery_enabled && (
                          <RouterLink
                            to="/recover-password"
                            className={`text-xs ${linkClassName}`}
                          >
                            {t({ zh: "忘记密码？", en: "Forgot password?" })}
                          </RouterLink>
                        )}
                      </div>
                      <FormControl>
                        <PasswordInput
                          {...field}
                          data-testid="password-input"
                          placeholder={t({
                            zh: "请输入密码",
                            en: "Enter your password",
                          })}
                          autoComplete="current-password"
                          className={`${inputClassName} pr-12`}
                          required
                          readOnly={loginMutation.isPending}
                        />
                      </FormControl>
                      <FormDescription className="sr-only">
                        {t({
                          zh: "请输入账号密码。",
                          en: "Enter your account password.",
                        })}
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
                  {loginMutation.isPending
                    ? t({ zh: "正在登录…", en: "Signing in…" })
                    : t({ zh: "登录工作台", en: "Sign in to workspace" })}
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
                    {t({ zh: "还没有账号？", en: "No account yet?" })}{" "}
                    <RouterLink to="/signup" className={linkClassName}>
                      {t({ zh: "注册账号", en: "Sign up" })}
                    </RouterLink>
                  </p>
                ) : (
                  <p>
                    {t({
                      zh: "教师与管理员账号由学校统一开通。",
                      en: "Teacher and admin accounts are provisioned by the school.",
                    })}
                  </p>
                )}
                {!options.data.password_recovery_enabled && (
                  <p>
                    {t({
                      zh: "忘记密码？请联系学校管理员重置。",
                      en: "Forgot your password? Contact your school administrator.",
                    })}
                  </p>
                )}
              </div>
            )}
          </TabsContent>
        </Tabs>
        <p role="status" aria-atomic="true" className="sr-only">
          {loginMutation.isPending
            ? t({
                zh: "正在验证账号，请稍候。",
                en: "Verifying your account, please wait.",
              })
            : ""}
        </p>
        {options.isError && (
          <p
            role="status"
            className="rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-xs leading-5 text-muted-foreground"
          >
            {t({
              zh: "入口信息暂未加载，仍可使用学号或邮箱登录。",
              en: "Options failed to load; you can still sign in with your ID or email.",
            })}
            <button
              type="button"
              className={`ml-1 disabled:opacity-50 ${linkClassName}`}
              disabled={options.isFetching}
              onClick={() => void options.refetch()}
            >
              {options.isFetching
                ? t({ zh: "重试中…", en: "Retrying…" })
                : t({ zh: "重试", en: "Retry" })}
            </button>
          </p>
        )}
        {options.data?.demo_enabled && <DemoEntry />}
      </div>
    </LoginLayout>
  )
}
