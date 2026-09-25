import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import { ArrowDown, ArrowUp, Minus } from "lucide-react"
import { ClassesService } from "@/client"
import TrailView from "@/components/Practice/TrailView"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { APP_NAME } from "@/config"

export const Route = createFileRoute("/t/$code/s/$studentId")({
  component: StudentDetailPage,
  head: () => ({
    meta: [{ title: `学生轨迹 - ${APP_NAME}` }],
  }),
})

function StudentDetailPage() {
  const { code, studentId } = useParams({ from: "/t/$code/s/$studentId" })

  const trailQuery = useQuery({
    queryKey: ["teacher", "trail", code, studentId],
    queryFn: () =>
      ClassesService.readStudentTrail({
        code: code.toUpperCase(),
        studentId,
      }),
  })

  const boardQuery = useQuery({
    queryKey: ["teacher", "board", code],
    queryFn: () => ClassesService.readClassBoard({ code: code.toUpperCase() }),
  })

  const boardRow = boardQuery.data?.students.find(
    (s) => s.student_id === studentId,
  )

  if (trailQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        正在加载学生轨迹…
      </div>
    )
  }
  if (trailQuery.isError || !trailQuery.data) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-muted-foreground">
        学生不存在。
        <Button variant="outline" asChild>
          <Link to="/t/$code" params={{ code }}>
            回面板
          </Link>
        </Button>
      </div>
    )
  }

  const trail = trailQuery.data
  const name = trail.suffix
    ? `${trail.display_name}·${trail.suffix}`
    : trail.display_name

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">{name}</h1>
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              课堂 {trail.classroom_code}
              {boardRow && (
                <>
                  <Badge variant="outline">
                    当前档 {boardRow.current_band}
                  </Badge>
                  {trail.band_change === "up" && (
                    <Badge variant="outline" className="text-primary">
                      <ArrowUp /> 升档
                    </Badge>
                  )}
                  {trail.band_change === "down" && (
                    <Badge variant="outline">
                      <ArrowDown /> 降档
                    </Badge>
                  )}
                  {trail.band_change === "keep" && (
                    <Badge variant="outline">
                      <Minus /> 维持
                    </Badge>
                  )}
                  {boardRow.inactive_days7 && (
                    <Badge variant="destructive">7 日未练</Badge>
                  )}
                </>
              )}
            </p>
          </div>
          <Button variant="outline" size="sm" asChild>
            <Link to="/t/$code" params={{ code }}>
              回面板
            </Link>
          </Button>
        </div>

        <TrailView trail={trail} />

        <p className="pb-6 text-center text-xs text-muted-foreground">
          老师不评分、不改分；以上均为系统参考数据。
        </p>
      </div>
    </div>
  )
}
