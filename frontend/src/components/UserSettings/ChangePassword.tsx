import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import { useMemo } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type UpdatePassword, UsersService } from "@/client"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { LoadingButton } from "@/components/ui/loading-button"
import { PasswordInput } from "@/components/ui/password-input"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { handleError } from "@/utils"

// 校验消息随语言切换：schema 在组件内按当前语言重建
function buildFormSchema(t: ReturnType<typeof useI18n>["t"]) {
  return z
    .object({
      current_password: z
        .string()
        .min(1, {
          message: t({ zh: "请输入密码", en: "Password is required" }),
        })
        .min(8, {
          message: t({
            zh: "密码至少需要 8 个字符",
            en: "Password must be at least 8 characters",
          }),
        }),
      new_password: z
        .string()
        .min(1, {
          message: t({ zh: "请输入密码", en: "Password is required" }),
        })
        .min(8, {
          message: t({
            zh: "密码至少需要 8 个字符",
            en: "Password must be at least 8 characters",
          }),
        }),
      confirm_password: z.string().min(1, {
        message: t({
          zh: "请再次输入密码",
          en: "Password confirmation is required",
        }),
      }),
    })
    .refine((data) => data.new_password === data.confirm_password, {
      message: t({
        zh: "两次输入的密码不一致",
        en: "The passwords don't match",
      }),
      path: ["confirm_password"],
    })
}

type FormData = z.infer<ReturnType<typeof buildFormSchema>>

const ChangePassword = () => {
  const { t } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const schema = useMemo(() => buildFormSchema(t), [t])
  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    mode: "onSubmit",
    criteriaMode: "all",
    defaultValues: {
      current_password: "",
      new_password: "",
      confirm_password: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: UpdatePassword) =>
      UsersService.updatePasswordMe({ requestBody: data }),
    onSuccess: () => {
      showSuccessToast(
        t({ zh: "密码已更新", en: "Password updated successfully" }),
      )
      form.reset()
    },
    onError: handleError.bind(showErrorToast),
  })

  const onSubmit = async (data: FormData) => {
    mutation.mutate(data)
  }

  return (
    <div className="max-w-md">
      <h3 className="text-lg font-semibold py-4">
        {t({ zh: "修改密码", en: "Change Password" })}
      </h3>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex flex-col gap-4"
        >
          <FormField
            control={form.control}
            name="current_password"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>
                  {t({ zh: "当前密码", en: "Current Password" })}
                </FormLabel>
                <FormControl>
                  <PasswordInput
                    data-testid="current-password-input"
                    placeholder="••••••••"
                    aria-invalid={fieldState.invalid}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="new_password"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>{t({ zh: "新密码", en: "New Password" })}</FormLabel>
                <FormControl>
                  <PasswordInput
                    data-testid="new-password-input"
                    placeholder="••••••••"
                    aria-invalid={fieldState.invalid}
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
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>
                  {t({ zh: "确认密码", en: "Confirm Password" })}
                </FormLabel>
                <FormControl>
                  <PasswordInput
                    data-testid="confirm-password-input"
                    placeholder="••••••••"
                    aria-invalid={fieldState.invalid}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <LoadingButton
            type="submit"
            loading={mutation.isPending}
            className="self-start"
          >
            {t({ zh: "更新密码", en: "Update Password" })}
          </LoadingButton>
        </form>
      </Form>
    </div>
  )
}

export default ChangePassword
