import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router"
import { ArrowRight, Clock, Compass, MessageCircle } from "lucide-react"
import { useMemo, useState } from "react"
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
import { useStudentGuard } from "@/hooks/useStudentGuard"
import { loadStudent } from "@/lib/classroom-student"
import { useI18n } from "@/lib/i18n"

export const Route = createFileRoute("/explore/$code")({
  component: ExplorePage,
  head: () => ({
    meta: [{ title: `主题探索 / Explore Topics - ${APP_NAME}` }],
  }),
})

function ExplorePage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/explore/$code" })
  const navigate = useNavigate({ from: "/explore/$code" })
  const student = loadStudent(code)
  const [selected, setSelected] = useState<PathUnit | null>(null)
  const [statusFilter, setStatusFilter] = useState("all")
  const [query, setQuery] = useState("")

  const pathQuery = useQuery({
    retry: 1,
    retryDelay: 500,
    queryKey: ["classroom", code, "path", student?.id],
    queryFn: () =>
      ClassesService.readLearningPath({
        code: code.toUpperCase(),
      }),
    enabled: student !== null,
  })

  const filteredUnits = useMemo(() => {
    const units = pathQuery.data?.units ?? []
    return units.filter((u) => {
      const done = (u.rounds_done ?? 0) > 0
      if (statusFilter === "done" && !done) return false
      if (statusFilter === "new" && done) return false
      if (
        query &&
        !`${u.title} ${u.topic}`.toLowerCase().includes(query.toLowerCase())
      )
        return false
      return true
    })
  }, [pathQuery.data, statusFilter, query])

  useStudentGuard(code, student, pathQuery)

  const exploreMutation = useMutation({
    mutationFn: (unitId: string) =>
      ClassesService.startExplore({
        code: code.toUpperCase(),
        requestBody: { unit_id: unitId },
      }),
    onSuccess: (data) => {
      // 进入练习页（explore session 计划由练习页通过 session_id 拉取）
      void navigate({
        to: "/p/$code",
        params: { code },
        search: { explore: data.session_id },
      })
    },
    onError: (err: { body?: { detail?: string } }) => {
      // 后端 detail 是中文稳定文案；英文环境给通用提示（与登录页同口径）
      const detail = err.body?.detail
      toast.error(
        detail
          ? t({
              zh: detail,
              en: "Couldn't start this topic, please try again",
            })
          : t({
              zh: "暂时无法开始这个主题",
              en: "Couldn't start this topic right now",
            }),
      )
    },
  })

  if (student === null) return null

  const units = pathQuery.data?.units ?? []

  return (
    <StudentShell active="explore" wide>
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {t({
              zh: "世界很大，想聊什么？",
              en: "The world is big — what would you like to talk about?",
            })}
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            {t({
              zh: "从喜欢的主题开始，让英语走进你的日常。自主练习也积累 XP 与星级，不占用课堂任务。",
              en: "Start with topics you love and bring English into your daily life. Self Practice also earns XP and stars, without touching classroom tasks.",
            })}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {(
            [
              ["all", t({ zh: "全部", en: "All" })],
              ["new", t({ zh: "未开始", en: "Not started" })],
              ["done", t({ zh: "已练过", en: "Practiced" })],
            ] as const
          ).map(([v, label]) => (
            <button
              key={v}
              type="button"
              onClick={() => setStatusFilter(v)}
              className={
                statusFilter === v
                  ? "rounded-full bg-primary px-4 py-1.5 text-xs font-semibold text-white"
                  : "rounded-full border border-border bg-card px-4 py-1.5 text-xs text-muted-foreground"
              }
            >
              {label}
            </button>
          ))}
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t({
              zh: "找一个喜欢的主题",
              en: "Find a topic you like",
            })}
            aria-label={t({ zh: "搜索主题", en: "Search topics" })}
            className="ml-auto h-9 rounded-full border border-border bg-card px-4 text-base"
          />
        </div>

        {pathQuery.isPending ? (
          <p className="py-10 text-center text-muted-foreground">
            {t({ zh: "正在加载…", en: "Loading…" })}
          </p>
        ) : pathQuery.isError ? (
          // 加载失败必须与"没有内容"区分开：网络错误提示重试，而不是误导学生去找老师
          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-10 text-center text-muted-foreground">
              {t({
                zh: "主题列表加载失败，请检查网络后重试。",
                en: "Failed to load topics — check your connection and retry.",
              })}
              <Button
                variant="outline"
                size="sm"
                onClick={() => void pathQuery.refetch()}
              >
                {t({ zh: "重试", en: "Retry" })}
              </Button>
            </CardContent>
          </Card>
        ) : units.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-muted-foreground">
              {t({
                zh: "还没有可探索的主题，请老师先在内容管理中添加单元。",
                en: "No topics to explore yet — your teacher needs to add units in content management first.",
              })}
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {filteredUnits.map((unit) => (
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
                    {t({
                      zh: `主题：${unit.topic}`,
                      en: `Topic: ${unit.topic}`,
                    })}
                  </p>
                  <div className="mt-3 flex items-center justify-between text-[11px] text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Clock className="size-3.5" />{" "}
                      {t({ zh: "约 10 分钟", en: "About 10 min" })}
                    </span>
                    <ArrowRight className="size-4" />
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        {units.length > 0 && filteredUnits.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground">
              {t({
                zh: "暂时没找到这个主题，试试「宠物」，或切换筛选。",
                en: 'No matching topic yet — try "pets", or switch the filter.',
              })}
            </CardContent>
          </Card>
        )}

        <Card>
          <CardContent className="flex items-start gap-2.5 py-4 text-sm text-muted-foreground">
            <Compass className="mt-0.5 size-4 shrink-0" />
            {t({
              zh: "主题探索是自主练习，不影响今日练习的进度。换主题前记得先完成当前一题。",
              en: "Explore Topics is self practice and doesn't affect Today's Practice progress. Finish your current item before switching topics.",
            })}
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
              {t({
                zh: "从 3 句听句复述开始，再做 2 道情景问答。",
                en: "Start with 3 Listen & Repeat sentences, then 2 Scenario Q&A questions.",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="h-40 overflow-hidden rounded-xl">
            <TopicArt topic={selected?.topic} />
          </div>
          <p className="text-xs text-muted-foreground">
            <MessageCircle className="mr-1 inline size-3.5" />
            {t({
              zh: "自主练习 · 同样积累 XP 与星级 · 不计入课堂完成率",
              en: "Self Practice · Earns XP and stars too · Not counted in classroom completion",
            })}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelected(null)}>
              {t({ zh: "再看看", en: "Keep browsing" })}
            </Button>
            <Button
              onClick={() =>
                selected && exploreMutation.mutate(selected.unit_id)
              }
              disabled={exploreMutation.isPending}
            >
              {t({ zh: "就聊这个", en: "Let's talk about this" })}
              <ArrowRight />
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </StudentShell>
  )
}
