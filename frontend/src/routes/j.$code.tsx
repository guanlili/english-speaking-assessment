import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router"
import { ArrowRight, ChartLine, Headphones, MessageCircle } from "lucide-react"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { ClassesService } from "@/client"
import { Logo } from "@/components/Common/Logo"
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
    .trim()
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
      void navigate({ to: "/home/$code", params: { code } })
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
      void navigate({ to: "/home/$code", params: { code } })
    },
    onError: () => {
      setError("进入失败：课堂码可能不对，请和老师核对")
    },
  })

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-7">
        <Logo asLink={false} />
        <span className="hidden text-xs text-muted-foreground sm:block">
          每一次开口，都是向前一步
        </span>
      </header>
      <main className="mx-auto grid w-full max-w-6xl flex-1 items-center gap-7 px-6 py-4 lg:py-10 lg:grid-cols-[1.2fr_1fr] lg:gap-20">
        <section>
          <span className="inline-flex rounded-full border border-primary/15 bg-secondary px-3 py-1.5 text-xs font-semibold text-primary">
            SpeakUp · 你的口语课堂
          </span>
          <h1 className="mt-4 text-3xl lg:mt-6 font-bold leading-tight tracking-tight md:text-5xl">
            从今天开始，
            <br />
            <span className="text-primary">自在开口表达。</span>
          </h1>
          <p className="mt-4 max-w-md text-sm leading-7 text-muted-foreground">
            跟随老师的节奏，听一听、说一说。
            <br />
            不必追求完美，每一次表达都值得鼓励。
          </p>
          <div className="mt-5 grid max-w-lg lg:mt-9 grid-cols-3 gap-4">
            {[
              { icon: Headphones, title: "听后复述", text: "积累自然表达" },
              { icon: MessageCircle, title: "情景问答", text: "分享你的想法" },
              { icon: ChartLine, title: "看见成长", text: "记录每次进步" },
            ].map((item) => (
              <div key={item.title}>
                <item.icon className="mb-3 size-5 text-primary" />
                <p className="text-sm font-semibold">{item.title}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.text}
                </p>
              </div>
            ))}
          </div>
        </section>
        <Card className="w-full border-border/80 py-8 shadow-xl shadow-primary/5 sm:p-3">
          <CardHeader>
            <span className="mb-2 text-xs font-semibold tracking-widest text-primary">
              JOIN YOUR CLASS
            </span>
            <CardTitle className="text-2xl">进入你的课堂</CardTitle>
            <CardDescription>
              课堂码{" "}
              <span className="font-mono font-semibold">
                {code.toUpperCase()}
              </span>
              · 请使用老师熟悉的名字
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Form {...form}>
              <form
                onSubmit={form.handleSubmit((values) =>
                  joinMutation.mutate(values.display_name.trim()),
                )}
                className="space-y-6"
              >
                <FormField
                  control={form.control}
                  name="display_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>你的名字</FormLabel>
                      <FormControl>
                        <Input
                          className="h-12 bg-background/60"
                          autoComplete="name"
                          placeholder="例如：李雷"
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                {error && <p className="text-sm text-destructive">{error}</p>}
                <LoadingButton
                  type="submit"
                  className="h-12 w-full"
                  loading={joinMutation.isPending}
                >
                  进入课堂 <ArrowRight className="size-4" />
                </LoadingButton>
              </form>
            </Form>
            <p className="mt-5 text-center text-xs leading-6 text-muted-foreground">
              无需注册账号 · 进入后即可查看老师安排的练习
            </p>
          </CardContent>
        </Card>
      </main>
      <footer className="px-6 py-6 text-center text-xs text-muted-foreground">
        SpeakUp 开口说 · 参考反馈仅用于学习，不代表官方考试成绩
      </footer>
    </div>
  )
}
