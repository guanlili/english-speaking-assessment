import { useQuery } from "@tanstack/react-query"
import { ClassesService, type ClassroomIssue } from "@/client"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"

const labels = {
  device: {
    zh: "麦克风异常：请协助检查权限和设备",
    en: "Microphone issue: check permissions and device",
  },
  audio: {
    zh: "音频播放异常：请检查音量或重试启用声音",
    en: "Audio issue: check sound or retry enabling audio",
  },
  upload: {
    zh: "录音提交异常：请在学生设备重试上传",
    en: "Submission issue: retry upload on the student device",
  },
  scoring_slow: {
    zh: "评分超过 2 分钟：请稍后刷新，勿重复上传",
    en: "Scoring over 2 minutes: refresh later; do not re-upload",
  },
  scoring_failed: {
    zh: "评分失败：请展开学生结果查看详情",
    en: "Scoring failed: expand the student results for details",
  },
} satisfies Record<ClassroomIssue["kind"], { zh: string; en: string }>

export function ClassroomIssues({
  code,
  onStudent,
}: {
  code: string
  onStudent: (id: string) => void
}) {
  const { t, lang } = useI18n()
  const query = useQuery({
    queryKey: ["teacher", "diagnostics", code],
    queryFn: () => ClassesService.readClassroomDiagnostics({ code }),
    refetchInterval: 5000,
    retry: 1,
  })
  const issues = query.data?.issues ?? []
  const students = new Set(issues.map((row) => row.student_id)).size
  return (
    <section
      className="space-y-3 rounded-2xl border bg-card p-5"
      aria-label={t({ zh: "课堂异常", en: "Classroom issues" })}
    >
      <h2 className="font-semibold">
        {t({
          zh: `课堂异常 · ${students} 人`,
          en: `Classroom issues · ${students} students`,
        })}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t({
          zh: "设备及提交问题为学生端最近 5 分钟内上报；未联网设备无法上报，未作答不等于设备异常。时间表示问题上报或本次评分开始时间。",
          en: "Device and submission issues are reported by students within the last 5 minutes. Offline devices cannot report; no answer does not mean a device issue. Times show report or scoring start time.",
        })}
      </p>
      {query.isError ? (
        <div role="alert">
          {t({
            zh: "异常状态获取失败，不能据此判断全班正常。",
            en: "Could not load issue status; class health is unknown.",
          })}
          <Button
            variant="outline"
            className="ml-2 min-h-11"
            onClick={() => void query.refetch()}
          >
            {t({ zh: "重试", en: "Retry" })}
          </Button>
        </div>
      ) : query.isPending ? (
        <p role="status">{t({ zh: "正在检查…", en: "Checking…" })}</p>
      ) : issues.length === 0 ? (
        <p className="text-sm">
          {t({ zh: "暂未发现已上报的异常。", en: "No reported issues found." })}
        </p>
      ) : (
        <ul className="space-y-3">
          {issues.map((row) => (
            <li
              key={`${row.student_id}:${row.kind}:${row.attempt_id ?? "device"}`}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3"
            >
              <div className="min-w-0 break-words">
                <p className="font-medium">{row.display_name}</p>
                <p className="text-sm">{t(labels[row.kind])}</p>
                <p className="text-xs text-muted-foreground">
                  {formatDateTime(row.observed_at, lang)}
                </p>
              </div>
              <Button variant="outline" className="min-h-11" asChild>
                <a
                  href={`#student-${row.student_id}`}
                  onClick={() => onStudent(row.student_id)}
                >
                  {t({ zh: "定位学生", en: "Find student" })}
                </a>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
