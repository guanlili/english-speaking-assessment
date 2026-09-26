import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router"
import { ArrowRight, Clock, Compass, MessageCircle } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import type { PathUnit } from "@/client"
import { ClassesService } from "@/client"
import StudentShell from "@/components/Practice/StudentShell"
import TopicArt from "@/components/Practice/TopicArt"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { APP_NAME } from "@/config"
import {
  clearStudent,
  isStudentNotFound,
  loadStudent,
} from "@/lib/classroom-student"

export const Route = createFileRoute("/explore/$code")({
  component: ExplorePage,
  head: () => ({ meta: [{ title: `主题探索 - ${APP_NAME}` }] }),
})

function ExplorePage() {
  const { code } = useParams({ from: "/explore/$code" })
  const navigate = useNavigate({ from: "/explore/$code" })
  const student = loadStudent(code)
  const [selected, setSelected] = useState<PathUnit | null>(null)

  useEffect(() => {
    if (student === null) {
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [student, code, navigate])

  const pathQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["classroom", code, "path", student?.id],
    queryFn: () =>
      ClassesService.readLearningPath({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    enabled: student !== null,
  })

  // 身份失效（清库/课堂重建后 404）：清除本地身份，引导重新进入
  useEffect(() => {
    if (pathQuery.isError && isStudentNotFound(pathQuery.error)) {
      clearStudent(code)
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [pathQuery.isError, pathQuery.error, code, navigate])

  const exploreMutation = useMutation({
    mutationFn: (unitId: string) =>
      ClassesService.startExplore({
        code: code.toUpperCase(),
        requestBody: {
          unit_id: unitId,
          student_id: student?.id as string,
        },
      }),
    onSuccess: (data) => {
      // 进入练习页（explore session 计划由练习页通过 session_id 拉取）
      void navigate({
        to: "/p/$code",
        params: { code },
        search: { explore: data.session_id },
      })
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(err.body?.detail ?? "暂时无法开始这个主题"),
  })

  if (student === null) return null

  const units = pathQuery.data?.units ?? []

  return (
    <StudentShell active="explore" wide>
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            世界很大，想聊什么？
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            从喜欢的话题开始，让英语走进你的日常。自由练习也积累 XP
            与星级，不占用课堂任务。
          </p>
        </div>

        {pathQuery.isPending ? (
          <p className="py-10 text-center text-muted-foreground">正在加载…</p>
        ) : units.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-muted-foreground">
              还没有可探索的主题，请老师先在内容管理中添加单元。
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {units.map((unit) => (
              <button
                key={unit.unit_id}
                type="button"
                onClick={() => setSelected(unit)}
                className="overflow-hidden rounded-2xl border border-border bg-card text-left transition hover:-translate-y-1 hover:shadow-lg"
              >
                <div className="relative h-32">
                  <TopicArt topic={unit.topic} />
                  {(unit.best_stars ?? 0) > 0 && (
                    <span className="absolute top-2.5 left-2.5 rounded-md bg-card/85 px-2 py-0.5 text-[10px] font-semibold text-primary">
                      ★ {unit.best_stars}
                    </span>
                  )}
                </div>
                <div className="p-4">
                  <h3 className="text-sm font-semibold">{unit.title}</h3>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    主题：{unit.topic}
                  </p>
                  <div className="mt-3 flex items-center justify-between text-[11px] text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Clock className="size-3.5" /> 约 10 分钟
                    </span>
                    <ArrowRight className="size-4" />
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        <Card>
          <CardContent className="flex items-start gap-2.5 py-4 text-sm text-muted-foreground">
            <Compass className="mt-0.5 size-4 shrink-0" />
            主题探索是自由练习，不覆盖你的课堂任务。换题前记得先完成当前一题。
          </CardContent>
        </Card>
      </div>

      {/* 主题预览弹窗 */}
      <Dialog
        open={selected !== null}
        onOpenChange={(o) => !o && setSelected(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{selected?.title}</DialogTitle>
            <DialogDescription>
              从 3 句听后复述开始，再回答 2 个开放问题。
            </DialogDescription>
          </DialogHeader>
          <div className="h-40 overflow-hidden rounded-xl">
            <TopicArt topic={selected?.topic} />
          </div>
          <p className="text-xs text-muted-foreground">
            <MessageCircle className="mr-1 inline size-3.5" />
            自由练习 · 同样积累 XP 与星级 · 不计入课堂完成率
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelected(null)}>
              再看看
            </Button>
            <Button
              onClick={() =>
                selected && exploreMutation.mutate(selected.unit_id)
              }
              disabled={exploreMutation.isPending}
            >
              就聊这个
              <ArrowRight />
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </StudentShell>
  )
}
