import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { ArrowLeft, ShieldCheck } from "lucide-react"
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
 * 平台运营登录（多租户 B3）：独立身份 + 独立 audience（typ=operator）。
 * 与学校登录完全分离——学校侧不再有跨校绕过账号（设计稿 §3.2）。
 * 运营 token 只被平台路由接受，学校业务端点一律 401。
 */
function PlatformLoginPage() {
  const { t } = useI18n()

  const schema = z.object({
    email: z
      .string()
      .trim()
      .min(1, { message: t({ zh: "请输入邮箱", en: "Enter your email" }) }),
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
    defaultValues: { email: "", password: "" },
  })

  const submit = useMutation({
    mutationFn: (data: FormData) =>
      LoginService.loginPlatformToken({
        bodyLoginLoginPlatformToken: {
          username: data.email,
          password: data.password,
        },
      }).then(async (response) => {
        const token = (response as unknown as { access_token: string })
          .access_token
        localStorage.setItem("access_token", token)
        localStorage.setItem("esa:role", "operator")
        localStorage.removeItem("esa:must-change-pw")
        // 运营会话的展示信息由 /login/platform/me 提供（useAuth 的
        // platformOperator 查询）；整页跳转清掉学校会话的内存缓存
        window.location.href = "/admin/dashboard"
        return null
      }),
    onError: (err) =>
      toast.error(
        extractErrorMessage(err) ||
          t({ zh: "登录失败，请重试", en: "Login failed, please retry" }),
      ),
  })

  return (
    <LoginLayout>
      <div className="mb-6 flex flex-col items-center gap-3">
        <div className="bg-primary/10 flex size-14 items-center justify-center rounded-2xl">
          <ShieldCheck className="text-primary size-7" aria-hidden="true" />
        </div>
        <div className="text-center">
          <h2 className="text-xl font-semibold tracking-tight">
            {t({ zh: "平台运营", en: "Platform Operator" })}
          </h2>
          <p className="text-muted-foreground mt-0.5 text-sm">
            {t({
              zh: "大盘 · 用户 · 平台目录管理",
              en: "Dashboard · Users · Platform catalog",
            })}
          </p>
          <p className="text-muted-foreground mt-2 text-xs">
            {t({
              zh: `${APP_NAME} · 运营入口`,
              en: `${APP_NAME} · Operator Portal`,
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
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-base">
                  {t({ zh: "邮箱", en: "Email" })}
                </FormLabel>
                <FormControl>
                  <Input
                    className="min-h-11 text-base"
                    type="email"
                    autoComplete="username"
                    placeholder="operator@example.com"
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

      <Button variant="ghost" className="mt-6 w-full" asChild>
        <a href="/login">
          <ArrowLeft className="mr-2 size-4" aria-hidden="true" />
          {t({ zh: "返回学校登录", en: "Back to school login" })}
        </a>
      </Button>
    </LoginLayout>
  )
}

export const Route = createFileRoute("/platform/login")({
  beforeLoad: () => {
    if (localStorage.getItem("access_token")) {
      throw redirect({ to: "/" })
    }
  },
  component: PlatformLoginPage,
})
