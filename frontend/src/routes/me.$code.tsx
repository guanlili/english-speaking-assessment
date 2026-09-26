import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import { ArrowDown, ArrowUp, Flame, Minus, Sparkles, Star } from "lucide-react"
import { useEffect } from "react"
import { ClassesService } from "@/client"
import TrailView from "@/components/Practice/TrailView"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { APP_NAME } from "@/config"
import { displayName, loadStudent } from "@/lib/classroom-student"

export const Route = createFileRoute("/me/$code")({
  component: MyTrailPage,
  head: () => ({
    meta: [{ title: `我的进步 - ${APP_NAME}` }],
  }),
})

function MyTrailPage() {
  const { code } = useParams({ from: "/me/$code" })
  const navigate = useNavigate({ from: "/me/$code" })
  const student = loadStudent(code)

  useEffect(() => {
    if (student === null) {
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [student, code, navigate])

  const todayQuery = useQuery({
    queryKey: ["classroom", code, "today", student?.id],
    queryFn: () =>
      ClassesService.readTodayPlan({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    enabled: student !== null,
  })

  const trailQuery = useQuery({
    queryKey: ["classroom", code, "trail", student?.id],
    queryFn: () =>
      ClassesService.readStudentTrail({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    enabled: student !== null,
  })

  if (student === null) return null

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-6">
        {todayQuery.data?.gamification && (
          <div className="flex flex-wrap items-center gap-4 rounded-lg border px-4 py-3">
            <span className="flex items-center gap-1 text-sm font-semibold">
              <Sparkles className="size-4 text-primary" />
              {todayQuery.data.gamification.xp} XP
            </span>
            <span className="flex items-center gap-1 text-sm text-muted-foreground">
              <Flame className="size-4 text-orange-500" />
              连胜 {todayQuery.data.gamification.streak_days} 天
            </span>
            <div className="ml-auto flex flex-wrap gap-2">
              {(todayQuery.data.gamification.badges ?? []).map((b) => (
                <Badge key={b.key} variant="secondary" title={b.description}>
                  <Star className="size-3" /> {b.label}
                </Badge>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">我的进步</h1>
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              {displayName(student)} · 课堂 {code.toUpperCase()}
              {trailQuery.data?.band_change === "up" && (
                <Badge variant="outline" className="text-primary">
                  <ArrowUp /> 升档
                </Badge>
              )}
              {trailQuery.data?.band_change === "down" && (
                <Badge variant="outline">
                  <ArrowDown /> 降档
                </Badge>
              )}
              {trailQuery.data?.band_change === "keep" && (
                <Badge variant="outline">
                  <Minus /> 维持
                </Badge>
              )}
            </p>
          </div>
          <Button variant="outline" size="sm" asChild>
            <Link to="/p/$code" params={{ code }}>
              回练习页
            </Link>
          </Button>
        </div>

        {trailQuery.isPending ? (
          <p className="py-10 text-center text-muted-foreground">正在加载…</p>
        ) : trailQuery.isError || !trailQuery.data ? (
          <p className="py-10 text-center text-muted-foreground">
            加载失败，请刷新重试。
          </p>
        ) : (
          <TrailView trail={trailQuery.data} />
        )}

        <p className="pb-6 text-center text-xs text-muted-foreground">
          参考数据，不是考试成绩或官方等级。
        </p>
      </div>
    </div>
  )
}
