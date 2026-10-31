import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { ArrowLeft, School } from "lucide-react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"
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
import { APP_NAME } from "@/config"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"

/**
 * 学校入口（多租户 B2）：/s/{school_slug}/login。
 * 登录前先经受限读取端点解析学校（仅名称，不含账号信息），登录请求带
 * school 字段按租户限定查找。同域方案，支持学校直发链接/二维码。
 */
function SchoolLoginPage() {
  const { t } = useI18n()
  const schoolSlug = Route.useParams().schoolSlug

  const schoolQuery = useQuery({
    queryKey: ["school-login-info", schoolSlug],
    queryFn: () =>
      LoginService.readSchoolLoginInfo({ slug: schoolSlug }).then(
        (r) =>
          r as unknown as {
            slug: string
            name_zh: string
            name_en: string | null
          },
      ),
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  const schema = z.object({
    account: z
      .string()
      .trim()
      .min(1, {
        message: t({ zh: "请输入学号或邮箱", en: "Enter student ID or email" }),
      }),
    password: z.string().min(8, {
      message: t({
        zh: "密码至少 8 位",
        en: "Password must be at least 8 characters",
      }),
    }),
  })
  type FormData = z.infer<typeof schema>

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { account: "", password: "" },
  })

  const submit = useMutation({
    mutationFn: (data: FormData) =>
      // 直接调 LoginService：school 是查询参数，loginMutation（useAuth）不透传
      LoginService.loginAccessToken({
        school: schoolSlug,
        bodyLoginLoginAccessToken: {
          username: data.account,
          password: data.password,
        },
      }).then(async (response) => {
        const token = (response as unknown as { access_token: string })
          .access_token
        localStorage.setItem("access_token", token)
        const { UsersService } = await import("@/client")
        const me = await UsersService.readUserMe()
        localStorage.setItem("esa:role", me.role ?? "teacher")
        localStorage.setItem(
          "esa:must-change-pw",
          me.must_change_password ? "1" : "0",
        )
        window.location.href = me.role === "student" ? "/join" : "/"
        return null
      }),
    onError: (err) => showErrorToastSafe(err),
  })

  const showErrorToastSafe = (err: unknown) => {
    toast.error(
      extractErrorMessage(err) ||
        t({ zh: "登录失败，请重试", en: "Login failed, please retry" }),
    )
  }

  if (schoolQuery.isPending) {
    return (
      <LoginLayout>
        <div className="flex min-h-[300px] items-center justify-center">
          <p className="text-muted-foreground text-sm">
            {t({ zh: "正在加载学校信息…", en: "Loading school information…" })}
          </p>
        </div>
      </LoginLayout>
    )
  }

  if (schoolQuery.isError || !schoolQuery.data) {
    return (
      <LoginLayout>
        <div className="flex min-h-[300px] flex-col items-center justify-center gap-4">
          <p className="text-destructive text-sm font-medium">
            {t({
              zh: "学校不存在或未开放，请检查链接是否正确",
              en: "School not found or not open. Please check the link.",
            })}
          </p>
          <Button variant="outline" asChild>
            <a href="/login">
              <ArrowLeft className="mr-2 size-4" aria-hidden="true" />
              {t({ zh: "返回通用登录", en: "Back to general login" })}
            </a>
          </Button>
        </div>
      </LoginLayout>
    )
  }

  const school = schoolQuery.data

  return (
    <LoginLayout>
      <div className="mb-6 flex flex-col items-center gap-3">
        <div className="bg-primary/10 flex size-14 items-center justify-center rounded-2xl">
          <School className="text-primary size-7" aria-hidden="true" />
        </div>
        <div className="text-center">
          <h2 className="text-xl font-semibold tracking-tight">
            {school.name_zh}
          </h2>
          {school.name_en && (
            <p className="text-muted-foreground mt-0.5 text-sm">
              {school.name_en}
            </p>
          )}
          <p className="text-muted-foreground mt-2 text-xs">
            {t({
              zh: `${APP_NAME} · 学校入口`,
              en: `${APP_NAME} · School Portal`,
            })}
          </p>
        </div>
      </div>

      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((data) => submit.mutate(data))}
          className="space-y-4"
          noValidate
        >
          <FormField
            control={form.control}
            name="account"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-base">
                  {t({ zh: "学号 / 邮箱", en: "Student ID / Email" })}
                </FormLabel>
                <FormControl>
                  <Input
                    className="min-h-11 text-base"
                    placeholder={t({
                      zh: "学号（学生）或邮箱（教师）",
                      en: "Student ID or email (teacher)",
                    })}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-base">
                  {t({ zh: "密码", en: "Password" })}
                </FormLabel>
                <FormControl>
                  <PasswordInput
                    className="min-h-11 text-base"
                    placeholder="••••••••"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <LoadingButton
            type="submit"
            className="w-full"
            size="lg"
            loading={submit.isPending}
          >
            {t({ zh: "登录", en: "Sign in" })}
          </LoadingButton>
        </form>
      </Form>

      <p className="text-muted-foreground mt-6 text-center text-xs">
        {t({
          zh: "遇到问题？请联系本校管理员",
          en: "Having trouble? Contact your school administrator",
        })}
      </p>
    </LoginLayout>
  )
}

export const Route = createFileRoute("/s/$schoolSlug/login")({
  beforeLoad: () => {
    if (localStorage.getItem("access_token")) {
      throw redirect({ to: "/" })
    }
  },
  component: SchoolLoginPage,
})
