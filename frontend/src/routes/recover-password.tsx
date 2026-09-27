import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { useRef } from "react"
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
import { handleError } from "@/utils"

const formSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, { message: "请输入邮箱地址" })
    .pipe(z.email({ message: "请输入有效的邮箱地址" })),
})

type FormData = z.infer<typeof formSchema>

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
        title: `找回密码 - ${APP_NAME}`,
      },
    ],
  }),
})

function RecoverPassword() {
  const loginOptions = useLoginOptions()
  const submissionInFlight = useRef(false)
  const recoveryEnabled =
    loginOptions.isSuccess &&
    loginOptions.data.password_recovery_enabled === true
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
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
        "如果该邮箱已注册，你将收到重置邮件，请检查收件箱及垃圾邮件",
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
          <h1 className="text-2xl font-bold">找回密码</h1>
          <p
            role={loginOptions.isError ? "alert" : "status"}
            className="text-sm text-muted-foreground"
          >
            {loginOptions.isPending
              ? "正在加载密码找回设置…"
              : loginOptions.isError
                ? "暂时无法获取密码找回设置，请重试。"
                : "暂未开放自助找回密码，请联系学校管理员重置密码。学生请使用课堂码进入。"}
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
            <h1 className="text-2xl font-bold">找回密码</h1>
          </div>

          <div className="grid gap-4">
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

            <LoadingButton
              type="submit"
              className="w-full"
              loading={mutation.isPending || form.formState.isSubmitting}
            >
              发送重置邮件
            </LoadingButton>
          </div>

          <div className="text-center text-sm">
            想起密码了？{" "}
            <RouterLink to="/login" className="underline underline-offset-4">
              返回登录
            </RouterLink>
          </div>
        </form>
      </Form>
    </AuthLayout>
  )
}
