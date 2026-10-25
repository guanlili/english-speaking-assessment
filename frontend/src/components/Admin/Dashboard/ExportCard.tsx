import { Download } from "lucide-react"
import { AdminService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"

/** 数据导出：三个口径的 CSV 下载（北京时间、BOM、Excel 直开）。 */
function ExportCard() {
  const { t } = useI18n()
  const { showErrorToast } = useCustomToast()

  const items = [
    {
      key: "attempts",
      label: t({ zh: "作答明细", en: "Attempt details" }),
      desc: t({
        zh: "每次录音一行：题目、转写、分数、AI 建议、教师批注",
        en: "One row per recording: item, transcript, scores, AI advice, teacher notes",
      }),
      download: () =>
        AdminService.exportAttemptsCsv({ days: 0 }).then((r) => r as string),
      filename: "usage-attempts.csv",
    },
    {
      key: "sessions",
      label: t({ zh: "练习轮次", en: "Practice rounds" }),
      desc: t({
        zh: "每轮练习一行：题数、均分、模考用时、切屏",
        en: "One row per round: items, averages, exam timing, tab switches",
      }),
      download: () =>
        AdminService.exportSessionsCsv({ days: 0 }).then((r) => r as string),
      filename: "usage-sessions.csv",
    },
    {
      key: "students",
      label: t({ zh: "学生汇总", en: "Student summary" }),
      desc: t({
        zh: "每个学生一行：作答量、均分、XP、连胜",
        en: "One row per student: volume, averages, XP, streaks",
      }),
      download: () => AdminService.exportStudentsCsv().then((r) => r as string),
      filename: "usage-students.csv",
    },
  ]

  const save = async (download: () => Promise<string>, filename: string) => {
    try {
      const text = await download()
      const blob = new Blob([text], { type: "text/csv;charset=utf-8" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      showErrorToast(
        t({ zh: "下载失败，请重试", en: "Download failed, retry" }),
      )
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t({ zh: "数据导出", en: "Data export" })}
        </CardTitle>
        <CardDescription>
          {t({
            zh: "全平台使用记录 CSV（北京时间，Excel 可直接打开）。",
            en: "Platform-wide usage CSVs (Beijing time, opens directly in Excel).",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 md:flex-row">
        {items.map((item) => (
          <div
            key={item.key}
            className="flex flex-1 items-start justify-between gap-3 rounded-xl border p-4"
          >
            <div>
              <p className="text-sm font-medium">{item.label}</p>
              <p className="mt-1 text-xs text-muted-foreground">{item.desc}</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="min-h-11 shrink-0"
              onClick={() => void save(item.download, item.filename)}
            >
              <Download className="size-4" aria-hidden="true" />
              {t({ zh: "下载", en: "Download" })}
            </Button>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

export default ExportCard
