import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { ClassesService } from "@/client"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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
import { loadStudent, saveStudent } from "@/lib/classroom-student"

const formSchema = z.object({
  display_name: z
    .string()
    .min(1, { message: "请输入你的名字" })
    .max(64, { message: "名字太长了" }),
})

type FormData = z.infer<typeof formSchema>

export const Route = createFileRoute("/j/$code")({
  component: JoinPage,
  head: () => ({
    meta: [{ title: `进入课堂 - ${APP_NAME}` }],
  }),
})

function JoinPage() {
  const { code } = useParams({ from: "/j/$code" })
  const navigate = useNavigate({ from: "/j/$code" })
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    defaultValues: { display_name: "" },
  })
  const [error, setError] = useState<string | null>(null)

  // 已在本课堂留过名：直接进练习页（BDD B：中途刷新仍是这个个人）
  useEffect(() => {
    if (loadStudent(code)) {
      void navigate({ to: "/p/$code", params: { code } })
    }
  }, [code, navigate])

  const joinMutation = useMutation({
    mutationFn: (display_name: string) =>
      ClassesService.joinClass({
        code: code.toUpperCase(),
        requestBody: { display_name },
      }),
    onSuccess: (student) => {
      saveStudent(code, student)
      void navigate({ to: "/p/$code", params: { code } })
    },
    onError: () => {
      setError("进入失败：课堂码可能不对，请和老师核对")
    },
  })

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">进入课堂</CardTitle>
          <CardDescription>
            课堂码{" "}
            <span className="font-mono font-semibold">
              {code.toUpperCase()}
            </span>
            ：输入你的名字开始今天的练习
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit((values) =>
                joinMutation.mutate(values.display_name.trim()),
              )}
              className="space-y-4"
            >
              <FormField
                control={form.control}
                name="display_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>你的名字</FormLabel>
                    <FormControl>
                      <Input placeholder="例如：李雷" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {error && <p className="text-sm text-destructive">{error}</p>}
              <LoadingButton
                type="submit"
                className="w-full"
                loading={joinMutation.isPending}
              >
                开始练习
              </LoadingButton>
            </form>
          </Form>
        </CardContent>
      </Card>
    </div>
  )
}
