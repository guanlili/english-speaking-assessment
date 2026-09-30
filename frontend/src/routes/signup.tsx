import { zodResolver } from "@hookform/resolvers/zod"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { useMemo, useRef } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
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
import { PasswordInput } from "@/components/ui/password-input"
import { APP_NAME } from "@/config"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"
import useLoginOptions from "@/hooks/useLoginOptions"
import { useI18n } from "@/lib/i18n"

// 校验消息随语言切换：schema 在组件内按当前语言重建
function buildFormSchema(t: ReturnType<typeof useI18n>["t"]) {
  return z
    .object({
      email: z
        .string()
        .trim()
        .min(1, {
          message: t({ zh: "请输入邮箱地址", en: "Enter your email" }),
        })
        .pipe(
          z.email({
            message: t({
              zh: "请输入有效的邮箱地址",
              en: "Enter a valid email address",
            }),
          }),
        ),
      full_name: z
        .string()
        .trim()
        .min(1, { message: t({ zh: "请输入姓名", en: "Enter your name" }) }),
      password: z
        .string()
        .min(1, { message: t({ zh: "请输入密码", en: "Enter your password" }) })
        .min(8, {
          message: t({
            zh: "密码至少需要 8 个字符",
            en: "Password must be at least 8 characters",
          }),
        }),
      confirm_password: z.string().min(1, {
        message: t({ zh: "请再次输入密码", en: "Enter the password again" }),
      }),
    })
    .refine((data) => data.password === data.confirm_password, {
      message: t({
        zh: "两次输入的密码不一致",
        en: "The passwords don't match",
      }),
      path: ["confirm_password"],
    })
}

type FormData = z.infer<ReturnType<typeof buildFormSchema>>

export const Route = createFileRoute("/signup")({
  component: SignUp,
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
        title: `注册账号 / Sign Up - ${APP_NAME}`,
      },
    ],
  }),
})

function SignUp() {
  const { t } = useI18n()
  const { signUpMutation } = useAuth()
  const loginOptions = useLoginOptions()
  const submissionInFlight = useRef(false)
  const registrationEnabled =
    loginOptions.isSuccess && loginOptions.data.registration_enabled === true
  const schema = useMemo(() => buildFormSchema(t), [t])
  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      email: "",
      full_name: "",
      password: "",
      confirm_password: "",
    },
  })

  const onSubmit = (data: FormData) => {
    if (
      !registrationEnabled ||
      signUpMutation.isPending ||
      submissionInFlight.current
    ) {
      return
    }

    submissionInFlight.current = true
    signUpMutation.mutate(
      {
        email: data.email,
        full_name: data.full_name,
        password: data.password,
      },
      {
        onSettled: () => {
          submissionInFlight.current = false
        },
      },
    )
  }

  if (!registrationEnabled) {
    return (
      <AuthLayout>
        <div className="flex flex-col gap-6 text-center">
          <h1 className="text-2xl font-bold">
            {t({ zh: "注册账号", en: "Sign Up" })}
          </h1>
          <p
            role={loginOptions.isError ? "alert" : "status"}
            className="text-sm text-muted-foreground"
          >
            {loginOptions.isPending
              ? t({
                  zh: "正在加载注册设置…",
                  en: "Loading sign-up settings…",
                })
              : loginOptions.isError
                ? t({
                    zh: "暂时无法获取注册设置，请重试。",
                    en: "Couldn't load sign-up settings. Please retry.",
                  })
                : t({
                    zh: "暂未开放自助注册，请联系学校管理员开通账号；学生请使用课堂码进入",
                    en: "Self sign-up is not available; ask your school administrator to create an account. Students join with a classroom code",
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
              {t({ zh: "注册账号", en: "Sign Up" })}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t({
                zh: "学生无需注册，请返回登录页使用课堂码进入。",
                en: "Students don't need an account — go back and join with a classroom code.",
              })}
            </p>
          </div>

          <div className="grid gap-4">
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t({ zh: "姓名", en: "Full Name" })}</FormLabel>
                  <FormControl>
                    <Input
                      data-testid="full-name-input"
                      placeholder={t({
                        zh: "请输入姓名",
                        en: "Enter your name",
                      })}
                      type="text"
                      autoComplete="name"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

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

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t({ zh: "密码", en: "Password" })}</FormLabel>
                  <FormControl>
                    <PasswordInput
                      data-testid="password-input"
                      placeholder={t({
                        zh: "请输入密码",
                        en: "Enter your password",
                      })}
                      autoComplete="new-password"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="confirm_password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    {t({ zh: "确认密码", en: "Confirm Password" })}
                  </FormLabel>
                  <FormControl>
                    <PasswordInput
                      data-testid="confirm-password-input"
                      placeholder={t({
                        zh: "请再次输入密码",
                        en: "Enter the password again",
                      })}
                      autoComplete="new-password"
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
              loading={signUpMutation.isPending || form.formState.isSubmitting}
            >
              {t({ zh: "注册", en: "Sign Up" })}
            </LoadingButton>
          </div>

          <div className="text-center text-sm">
            {t({ zh: "已有账号？", en: "Already have an account?" })}{" "}
            <RouterLink to="/login" className="underline underline-offset-4">
              {t({ zh: "返回登录", en: "Back to Sign In" })}
            </RouterLink>
          </div>
        </form>
      </Form>
    </AuthLayout>
  )
}
