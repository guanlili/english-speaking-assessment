import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { useMemo, useRef } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { LoginService } from "@/client"
import { AuthLayout } from "@/components/Common/AuthLayout"
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
import { APP_NAME } from "@/config"
import { isLoggedIn } from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import useLoginOptions from "@/hooks/useLoginOptions"
import { useI18n } from "@/lib/i18n"
import { handleError } from "@/utils"

// 校验消息随语言切换：schema 在组件内按当前语言重建
function buildFormSchema(t: ReturnType<typeof useI18n>["t"]) {
  return z.object({
    email: z
      .string()
      .trim()
      .min(1, { message: t({ zh: "请输入邮箱地址", en: "Enter your email" }) })
      .pipe(
        z.email({
          message: t({
            zh: "请输入有效的邮箱地址",
            en: "Enter a valid email address",
          }),
        }),
      ),
  })
}

type FormData = z.infer<ReturnType<typeof buildFormSchema>>

export const Route = createFileRoute("/recover-password")({
  component: RecoverPassword,
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
        title: `找回密码 / Recover Password - ${APP_NAME}`,
      },
    ],
  }),
})

function RecoverPassword() {
  const { t } = useI18n()
  const loginOptions = useLoginOptions()
  const submissionInFlight = useRef(false)
  const recoveryEnabled =
    loginOptions.isSuccess &&
    loginOptions.data.password_recovery_enabled === true
  const schema = useMemo(() => buildFormSchema(t), [t])
  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: "",
    },
  })
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const recoverPassword = async (data: FormData) => {
    await LoginService.recoverPassword({
      email: data.email,
    })
  }

  const mutation = useMutation({
    mutationFn: recoverPassword,
    onSuccess: () => {
      showSuccessToast(
        t({
          zh: "如果该邮箱已注册，你将收到重置邮件，请检查收件箱及垃圾邮件",
          en: "If that email is registered, a reset message is on its way — check your inbox and spam folder",
        }),
      )
      form.reset()
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      submissionInFlight.current = false
    },
  })

  const onSubmit = (data: FormData) => {
    if (!recoveryEnabled || mutation.isPending || submissionInFlight.current) {
      return
    }
    submissionInFlight.current = true
    mutation.mutate(data)
  }

  if (!recoveryEnabled) {
    return (
      <AuthLayout>
        <div className="flex flex-col gap-6 text-center">
          <h1 className="text-2xl font-bold">
            {t({ zh: "找回密码", en: "Recover Password" })}
          </h1>
          <p
            role={loginOptions.isError ? "alert" : "status"}
            className="text-sm text-muted-foreground"
          >
            {loginOptions.isPending
              ? t({
                  zh: "正在加载密码找回设置…",
                  en: "Loading password recovery settings…",
                })
              : loginOptions.isError
                ? t({
                    zh: "暂时无法获取密码找回设置，请重试。",
                    en: "Couldn't load password recovery settings. Please retry.",
                  })
                : t({
                    zh: "暂未开放自助找回密码，请联系学校管理员重置密码。学生请使用课堂码进入。",
                    en: "Self-service recovery is not available; ask your school administrator to reset your password. Students join with a classroom code.",
                  })}
          </p>
          {loginOptions.isError && (
            <LoadingButton
              type="button"
              loading={loginOptions.isFetching}
              onClick={() => void loginOptions.refetch()}
            >
              {t({ zh: "重试", en: "Retry" })}
            </LoadingButton>
          )}
          <Button asChild variant="outline">
            <RouterLink to="/login">
              {t({ zh: "返回登录", en: "Back to Sign In" })}
            </RouterLink>
          </Button>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <Form {...form}>
        <form
          noValidate
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex flex-col gap-6"
        >
          <div className="flex flex-col items-center gap-2 text-center">
            <h1 className="text-2xl font-bold">
              {t({ zh: "找回密码", en: "Recover Password" })}
            </h1>
          </div>

          <div className="grid gap-4">
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t({ zh: "邮箱", en: "Email" })}</FormLabel>
                  <FormControl>
                    <Input
                      data-testid="email-input"
                      placeholder={t({
                        zh: "请输入邮箱地址",
                        en: "Enter your email",
                      })}
                      type="email"
                      autoComplete="username"
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
              loading={mutation.isPending || form.formState.isSubmitting}
            >
              {t({ zh: "发送重置邮件", en: "Send Recovery Email" })}
            </LoadingButton>
          </div>

          <div className="text-center text-sm">
            {t({ zh: "想起密码了？", en: "Remembered your password?" })}{" "}
            <RouterLink to="/login" className="underline underline-offset-4">
              {t({ zh: "返回登录", en: "Back to Sign In" })}
            </RouterLink>
          </div>
        </form>
      </Form>
    </AuthLayout>
  )
}
