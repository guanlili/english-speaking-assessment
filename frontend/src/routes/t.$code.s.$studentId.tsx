import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import { ApiError, ClassesService } from "@/client"
import TrailView from "@/components/Practice/TrailView"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { APP_NAME } from "@/config"
import { useI18n } from "@/lib/i18n"

export const Route = createFileRoute("/t/$code/s/$studentId")({
  component: StudentDetailPage,
  head: () => ({
    meta: [{ title: `进步轨迹 / Progress Trail - ${APP_NAME}` }],
  }),
})

function StudentDetailPage() {
  const { t } = useI18n()
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
        {t({ zh: "正在加载进步轨迹…", en: "Loading progress trail…" })}
      </div>
    )
  }
  if (trailQuery.isError || !trailQuery.data) {
    const status =
      trailQuery.error instanceof ApiError ? trailQuery.error.status : undefined
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-muted-foreground">
        {status === 403
          ? t({
              zh: "你还不是这个课堂的授权教师，无法查看学生数据。",
              en: "You are not an owner teacher of this classroom and cannot view student data.",
            })
          : status === 404
            ? t({ zh: "学生不存在。", en: "Student not found." })
            : t({
                zh: "进步轨迹加载失败，请稍后重试。",
                en: "Failed to load the progress trail, please try again later.",
              })}
        <Button variant="outline" asChild>
          <Link to="/t/$code" params={{ code }}>
            {t({ zh: "回面板", en: "Back to Dashboard" })}
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
              {t({
                zh: `课堂 ${trail.classroom_code}`,
                en: `Classroom ${trail.classroom_code}`,
              })}
              {boardRow?.inactive_days7 && (
                <Badge variant="destructive">
                  {t({ zh: "7 日未练", en: "Inactive 7 Days" })}
                </Badge>
              )}
            </p>
          </div>
          <Button variant="outline" size="sm" asChild>
            <Link to="/t/$code" params={{ code }}>
              {t({ zh: "回面板", en: "Back to Dashboard" })}
            </Link>
          </Button>
        </div>

        <TrailView trail={trail} />

        <p className="pb-6 text-center text-xs text-muted-foreground">
          {t({
            zh: "老师不评分、不改分；以上均为系统参考数据。",
            en: "Teachers don't grade or change scores; everything above is system reference data.",
          })}
        </p>
      </div>
    </div>
  )
}
