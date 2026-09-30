import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type UserCreate, UsersService } from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { handleError } from "@/utils"

// 校验消息随语言切换：schema 在组件内按当前语言重建
function buildFormSchema(t: ReturnType<typeof useI18n>["t"]) {
  return z
    .object({
      // 学生账号走「我的课堂 → 导入学生」批量建号；此处建教师/管理员
      email: z.email({
        message: t({
          zh: "请输入有效的邮箱地址",
          en: "Enter a valid email address",
        }),
      }),
      full_name: z.string().optional(),
      role: z.enum(["teacher", "admin"]),
      password: z
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
          en: "Please confirm your password",
        }),
      }),
      is_active: z.boolean(),
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

const AddUser = () => {
  const { t } = useI18n()
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const schema = useMemo(() => buildFormSchema(t), [t])

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      email: "",
      full_name: "",
      role: "teacher",
      password: "",
      confirm_password: "",
      is_active: true,
    },
  })

  const mutation = useMutation({
    mutationFn: (data: UserCreate) =>
      UsersService.createUser({ requestBody: data }),
    onSuccess: () => {
      showSuccessToast(
        t({ zh: "用户创建成功", en: "User created successfully" }),
      )
      form.reset()
      setIsOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const onSubmit = (data: FormData) => {
    const { confirm_password: _, ...submitData } = data
    mutation.mutate(submitData)
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button className="my-4">
          <Plus className="mr-2" />
          {t({ zh: "添加用户", en: "Add User" })}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t({ zh: "添加用户", en: "Add User" })}</DialogTitle>
          <DialogDescription>
            {t({
              zh: "在下方填写表单，为系统新增用户。",
              en: "Fill in the form below to add a new user to the system.",
            })}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {t({ zh: "邮箱", en: "Email" })}{" "}
                      <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder={t({ zh: "邮箱", en: "Email" })}
                        type="email"
                        {...field}
                        required
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="full_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t({ zh: "姓名", en: "Full Name" })}</FormLabel>
                    <FormControl>
                      <Input
                        placeholder={t({ zh: "姓名", en: "Full name" })}
                        type="text"
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
                    <FormLabel>
                      {t({ zh: "设置密码", en: "Set Password" })}{" "}
                      <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder={t({ zh: "密码", en: "Password" })}
                        type="password"
                        {...field}
                        required
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
                      {t({ zh: "确认密码", en: "Confirm Password" })}{" "}
                      <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder={t({ zh: "密码", en: "Password" })}
                        type="password"
                        {...field}
                        required
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="role"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {t({ zh: "角色", en: "Role" })}{" "}
                      <span className="text-destructive">*</span>
                    </FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="teacher">
                          {t({ zh: "教师", en: "Teacher" })}
                        </SelectItem>
                        <SelectItem value="admin">
                          {t({ zh: "管理员", en: "Admin" })}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="is_active"
                render={({ field }) => (
                  <FormItem className="flex items-center gap-3 space-y-0">
                    <FormControl>
                      <Checkbox
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                    <FormLabel className="font-normal">
                      {t({ zh: "启用？", en: "Is active?" })}
                    </FormLabel>
                  </FormItem>
                )}
              />
            </div>

            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline" disabled={mutation.isPending}>
                  {t({ zh: "取消", en: "Cancel" })}
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                {t({ zh: "保存", en: "Save" })}
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default AddUser
