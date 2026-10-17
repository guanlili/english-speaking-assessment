import { useQuery } from "@tanstack/react-query"
import { type BoardStudent, ClassesService } from "@/client"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

const labels = {
  entered: { zh: "已进入课堂", en: "In classroom" },
  recording: { zh: "正在录音", en: "Recording" },
  uploading: { zh: "正在上传", en: "Uploading" },
  idle: { zh: "正在练习", en: "Practicing" },
  unknown: { zh: "暂无近期状态", en: "No recent status" },
}
export function ClassroomLiveStatus({
  code,
  students,
  onStudent,
}: {
  code: string
  students: BoardStudent[]
  onStudent: (id: string) => void
}) {
  const { t } = useI18n()
  const query = useQuery({
    queryKey: ["teacher", "presence", code],
    queryFn: () => ClassesService.readClassroomPresence({ code }),
    refetchInterval: 5000,
  })
  return (
    <section className="space-y-3 rounded-2xl border bg-card p-5">
      <h2 className="font-semibold">
        {t({ zh: "课堂实时状态", en: "Live classroom status" })}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t({
          zh: "状态来自近 90 秒内的学生端上报；设备自检结果保留 2 小时。暂无近期状态不代表离线。",
          en: "Status is self-reported within 90 seconds; device checks last 2 hours. Missing status does not mean offline.",
        })}
      </p>
      {query.data && (
        <p className="text-sm font-medium">
          {t({
            zh: `录音 ${query.data.filter((row) => row.activity === "recording").length} 人 · 上传 ${query.data.filter((row) => row.activity === "uploading").length} 人 · 评分中 ${students.filter((row) => row.has_pending).length} 人 · 已完成 ${students.filter((row) => row.total_count > 0 && row.done_count === row.total_count).length} 人`,
            en: `${query.data.filter((row) => row.activity === "recording").length} recording · ${query.data.filter((row) => row.activity === "uploading").length} uploading · ${students.filter((row) => row.has_pending).length} scoring · ${students.filter((row) => row.total_count > 0 && row.done_count === row.total_count).length} completed`,
          })}
        </p>
      )}
      {query.isError ? (
        <Button
          variant="outline"
          className="min-h-11"
          onClick={() => void query.refetch()}
        >
          {t({ zh: "状态加载失败，重试", en: "Status unavailable. Retry" })}
        </Button>
      ) : query.isPending ? (
        <p role="status">{t({ zh: "正在加载…", en: "Loading…" })}</p>
      ) : (
        <ul className="grid max-h-80 gap-2 overflow-y-auto sm:grid-cols-2 xl:grid-cols-3">
          {query.data?.map((row) => {
            const student = students.find(
              (s) => s.student_id === row.student_id,
            )
            const completed =
              student &&
              student.total_count > 0 &&
              student.done_count === student.total_count
            return (
              <li key={row.student_id}>
                <Button
                  asChild
                  variant="outline"
                  className="h-auto min-h-11 w-full justify-start whitespace-normal p-3 text-left"
                  onClick={() => onStudent(row.student_id)}
                >
                  <a href={`#student-${row.student_id}`}>
                    <span className="min-w-0 break-words">
                      {row.display_name} ·{" "}
                      {completed
                        ? t({ zh: "已完成", en: "Completed" })
                        : student?.has_pending
                          ? t({ zh: "评分中", en: "Scoring" })
                          : t(labels[row.activity])}
                      <span className="mt-1 block text-xs text-muted-foreground">
                        {row.device_check === "passed"
                          ? t({ zh: "设备自检通过", en: "Device check passed" })
                          : row.device_check === "failed"
                            ? t({
                                zh: "设备自检异常",
                                en: "Device check failed",
                              })
                            : t({
                                zh: "尚无近期设备自检",
                                en: "No recent device check",
                              })}
                      </span>
                    </span>
                  </a>
                </Button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
