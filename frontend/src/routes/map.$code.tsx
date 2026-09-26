import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import { ChevronRight, Lock, Star } from "lucide-react"
import { useEffect } from "react"
import { ClassesService } from "@/client"
import StudentShell from "@/components/Practice/StudentShell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { APP_NAME } from "@/config"
import { displayName, loadStudent } from "@/lib/classroom-student"

export const Route = createFileRoute("/map/$code")({
  component: MapPage,
  head: () => ({ meta: [{ title: `关卡地图 - ${APP_NAME}` }] }),
})

function MapPage() {
  const { code } = useParams({ from: "/map/$code" })
  const navigate = useNavigate({ from: "/map/$code" })
  const student = loadStudent(code)

  useEffect(() => {
    if (student === null) {
      void navigate({ to: "/j/$code", params: { code } })
    }
  }, [student, code, navigate])

  const pathQuery = useQuery({
    queryKey: ["classroom", code, "path", student?.id],
    queryFn: () =>
      ClassesService.readLearningPath({
        code: code.toUpperCase(),
        studentId: student?.id as string,
      }),
    enabled: student !== null,
  })

  if (student === null) return null

  return (
    <StudentShell active="map">
      <div className="mx-auto flex w-full max-w-md flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">关卡地图</h1>
            <p className="text-sm text-muted-foreground">
              {displayName(student)} ·{" "}
              {pathQuery.data?.assignment
                ? `今日指派 ${pathQuery.data.assignment.title}`
                : "完成一关解锁下一关"}
            </p>
          </div>
          <Button variant="outline" size="sm" asChild>
            <Link to="/p/$code" params={{ code }}>
              今日练习
            </Link>
          </Button>
        </div>

        {pathQuery.isPending ? (
          <p className="py-10 text-center text-muted-foreground">正在加载…</p>
        ) : pathQuery.isError || !pathQuery.data ? (
          <p className="py-10 text-center text-muted-foreground">
            加载失败，请刷新重试。
          </p>
        ) : (
          pathQuery.data.units.map((unit, index) => (
            <Card
              key={unit.unit_id}
              className={
                unit.locked
                  ? "opacity-60"
                  : "cursor-pointer transition hover:border-primary/50 hover:shadow-md"
              }
              onClick={() => {
                if (!unit.locked) {
                  void navigate({ to: "/p/$code", params: { code } })
                }
              }}
            >
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <span className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">
                      {index + 1}
                    </span>
                    {unit.title}
                  </CardTitle>
                  {unit.locked ? (
                    <Lock className="size-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="size-4 text-muted-foreground" />
                  )}
                </div>
                <CardDescription>主题：{unit.topic}</CardDescription>
              </CardHeader>
              <CardContent className="flex items-center justify-between">
                <div className="flex items-center gap-1">
                  {[1, 2, 3].map((n) => (
                    <Star
                      key={n}
                      className={
                        unit.best_stars != null && n <= unit.best_stars
                          ? "size-4 fill-yellow-400 text-yellow-400"
                          : "size-4 text-muted-foreground/30"
                      }
                    />
                  ))}
                </div>
                {(unit.rounds_done ?? 0) > 0 ? (
                  <Badge variant="secondary">
                    已完成 {unit.rounds_done ?? 0} 轮
                  </Badge>
                ) : unit.locked ? (
                  <Badge variant="outline">🔒 未解锁</Badge>
                ) : (
                  <Badge variant="outline">开始</Badge>
                )}
              </CardContent>
            </Card>
          ))
        )}

        <p className="pb-6 text-center text-xs text-muted-foreground">
          {pathQuery.data?.assignment
            ? `📌 老师今日指派：${pathQuery.data.assignment.title}（练习页同步使用）`
            : "老师未指派时按个人关卡进度练习；星级只和自己比。"}
        </p>
      </div>
    </StudentShell>
  )
}
