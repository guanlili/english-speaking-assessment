import { zodResolver } from "@hookform/resolvers/zod"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { useRef } from "react"
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

const formSchema = z
  .object({
    email: z
      .string()
      .trim()
      .min(1, { message: "请输入邮箱地址" })
      .pipe(z.email({ message: "请输入有效的邮箱地址" })),
    full_name: z.string().trim().min(1, { message: "请输入姓名" }),
    password: z
      .string()
      .min(1, { message: "请输入密码" })
      .min(8, { message: "密码至少需要 8 个字符" }),
    confirm_password: z.string().min(1, { message: "请再次输入密码" }),
  })
  .refine((data) => data.password === data.confirm_password, {
    message: "两次输入的密码不一致",
    path: ["confirm_password"],
  })

type FormData = z.infer<typeof formSchema>

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
        title: `注册账号 - ${APP_NAME}`,
      },
    ],
  }),
})

function SignUp() {
  const { signUpMutation } = useAuth()
  const loginOptions = useLoginOptions()
  const submissionInFlight = useRef(false)
  const registrationEnabled =
    loginOptions.isSuccess && loginOptions.data.registration_enabled === true
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
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
          <h1 className="text-2xl font-bold">注册账号</h1>
          <p
            role={loginOptions.isError ? "alert" : "status"}
            className="text-sm text-muted-foreground"
          >
            {loginOptions.isPending
              ? "正在加载注册设置…"
              : loginOptions.isError
                ? "暂时无法获取注册设置，请重试。"
                : "暂未开放自助注册，请联系学校管理员开通账号；学生请使用课堂码进入"}
          </p>
          {loginOptions.isError && (
            <LoadingButton
              type="button"
              loading={loginOptions.isFetching}
              onClick={() => void loginOptions.refetch()}
            >
              重试
            </LoadingButton>
          )}
          <Button asChild variant="outline">
            <RouterLink to="/login">返回登录</RouterLink>
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
            <h1 className="text-2xl font-bold">注册账号</h1>
            <p className="text-sm text-muted-foreground">
              学生无需注册，请返回登录页使用课堂码进入。
            </p>
          </div>

          <div className="grid gap-4">
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>姓名</FormLabel>
                  <FormControl>
                    <Input
                      data-testid="full-name-input"
                      placeholder="请输入姓名"
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
                  <FormLabel>邮箱</FormLabel>
                  <FormControl>
                    <Input
                      data-testid="email-input"
                      placeholder="请输入邮箱地址"
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
                  <FormLabel>密码</FormLabel>
                  <FormControl>
                    <PasswordInput
                      data-testid="password-input"
                      placeholder="请输入密码"
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
                  <FormLabel>确认密码</FormLabel>
                  <FormControl>
                    <PasswordInput
                      data-testid="confirm-password-input"
                      placeholder="请再次输入密码"
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
              注册
            </LoadingButton>
          </div>

          <div className="text-center text-sm">
            已有账号？{" "}
            <RouterLink to="/login" className="underline underline-offset-4">
              返回登录
            </RouterLink>
          </div>
        </form>
      </Form>
    </AuthLayout>
  )
}
