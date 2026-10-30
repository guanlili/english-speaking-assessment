import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Download, RefreshCw } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import {
  ClassesService,
  type ClassroomExercisePublic,
  type ClassroomPublic,
  type ExportCreate,
  type ExportJobPublic,
  ExportsService,
  StudentsService,
} from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { exportsQueryKey, useExports } from "@/hooks/useExports"
import { exportJobMessage, exportStatusLabel } from "@/lib/export-copy"
import { useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"
import { extractErrorMessage, handleError } from "@/utils"

const API_BASE = import.meta.env.VITE_API_URL ?? ""

function ymd(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${date.getFullYear()}-${month}-${day}`
}

function shiftDays(days: number): string {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return ymd(date)
}

function isPast(iso: string | null): boolean {
  if (!iso) return false
  return new Date(iso).getTime() <= Date.now()
}

function isPdfJob(job: ExportJobPublic): boolean {
  const kind = job.kind ?? job.filter?.kind
  return kind === "student_report_pdf" || kind === "class_report_pdf"
}

function isClassReportJob(job: ExportJobPublic): boolean {
  return (job.kind ?? job.filter?.kind) === "class_report_pdf"
}

async function saveZip(job: ExportJobPublic): Promise<void> {
  const token = localStorage.getItem("access_token") || ""
  const response = await fetch(
    `${API_BASE}/api/v1/exports/${job.id}/download`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  )
  if (!response.ok) {
    let detail = response.status === 410 ? "export_expired" : "export_not_ready"
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === "string") detail = body.detail
    } catch {
      // 非 JSON 错误保持状态码映射
    }
    throw new Error(detail)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = job.download_name || "BELP_export.zip"
  link.click()
  URL.revokeObjectURL(url)
}

export function ExportCenter({ mode }: { mode: "self" | "classroom" }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const jobs = useExports()
  const previous = useRef<Map<string, string>>(new Map())
  const [fromDate, setFromDate] = useState(
    // 含今天共 7 个日历日，与「最近 7 天」一致
    mode === "classroom" ? shiftDays(-6) : "",
  )
  const [toDate, setToDate] = useState(
    mode === "classroom" ? ymd(new Date()) : "",
  )
  const [classroomId, setClassroomId] = useState("")
  const [exerciseId, setExerciseId] = useState("")
  const [groupByItem, setGroupByItem] = useState(true)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [exportKind, setExportKind] = useState<
    "audio_zip" | "student_report_pdf" | "class_report_pdf"
  >("audio_zip")
  const [reportDays, setReportDays] = useState(90)
  const [reportClassroomId, setReportClassroomId] = useState("")

  const classrooms = useQuery({
    queryKey: ["my-classrooms"],
    queryFn: () => ClassesService.listMyClassrooms(),
    enabled: mode === "classroom",
  })
  const enrollments = useQuery({
    queryKey: ["my-enrollments"],
    queryFn: () => StudentsService.listMyEnrollments(),
    enabled: mode === "self" && exportKind === "student_report_pdf",
  })
  const selected = useMemo(
    () =>
      (classrooms.data ?? []).find(
        (room: ClassroomPublic) => room.id === classroomId,
      ),
    [classrooms.data, classroomId],
  )
  const exercises = useQuery({
    queryKey: ["teacher", "exercises", selected?.code],
    queryFn: () =>
      ClassesService.listClassroomExercises({
        code: (selected?.code ?? "").toUpperCase(),
      }),
    enabled: mode === "classroom" && Boolean(selected?.code),
  })

  useEffect(() => {
    const rows = enrollments.data ?? []
    if (!reportClassroomId && rows[0]) {
      setReportClassroomId(rows[0].classroom_id)
    }
  }, [enrollments.data, reportClassroomId])

  useEffect(() => {
    const rows = jobs.data?.data ?? []
    for (const job of rows) {
      const prior = previous.current.get(job.id)
      if (prior && prior !== job.status) {
        if (job.status === "succeeded") {
          showSuccessToast(
            isPdfJob(job)
              ? t({
                  zh: "学情报告已准备好，可以在下载中心保存。",
                  en: "Your learning report is ready in the download center.",
                })
              : t({
                  zh: "录音包已准备好，可以在下载中心保存。",
                  en: "Your audio package is ready in the download center.",
                }),
          )
        } else if (job.status === "failed") {
          showErrorToast(exportJobMessage(job.error, t))
        }
      }
      previous.current.set(job.id, job.status)
    }
  }, [jobs.data, showErrorToast, showSuccessToast, t])

  const refresh = () =>
    void queryClient.invalidateQueries({ queryKey: exportsQueryKey })

  const createJob = useMutation({
    mutationFn: (body: ExportCreate) =>
      ExportsService.createExport({ exportCreate: body }),
    onSuccess: (job) => {
      if (job.status === "failed")
        showErrorToast(exportJobMessage(job.error, t))
      else if (job.status === "succeeded") {
        showSuccessToast(
          isPdfJob(job)
            ? t({
                zh: "学情报告已准备好，可以下载。",
                en: "Your learning report is ready to download.",
              })
            : t({
                zh: "录音包已准备好，可以下载。",
                en: "Your audio package is ready to download.",
              }),
        )
      } else {
        showSuccessToast(
          isPdfJob(job)
            ? t({
                zh: "已开始生成学情报告。完成后会出现在下面的列表里。",
                en: "The learning report is being built. It will show up in the list below.",
              })
            : t({
                zh: "已开始打包。完成后会在下面列表里出现，并提示你。",
                en: "Packing has started. The list below updates when it is ready.",
              }),
        )
      }
      setConfirmOpen(false)
      setConfirmed(false)
      refresh()
    },
    onError: handleError.bind(showErrorToast),
  })

  const retryJob = useMutation({
    mutationFn: (job_id: string) => ExportsService.retryExport({ job_id }),
    onSuccess: (job) => {
      showSuccessToast(
        isPdfJob(job)
          ? t({
              zh: "已重新生成学情报告。",
              en: "The learning report is being built again.",
            })
          : t({ zh: "已重新开始打包。", en: "Packing has started again." }),
      )
      refresh()
    },
    onError: handleError.bind(showErrorToast),
  })

  const submit = (confirmFlag: boolean) => {
    if (mode === "classroom" && !classroomId) {
      showErrorToast(
        t({ zh: "请先选择课堂。", en: "Choose a classroom first." }),
      )
      return
    }
    if (
      (mode === "classroom" || exportKind === "student_report_pdf") &&
      fromDate &&
      toDate
    ) {
      const span =
        (new Date(`${toDate}T00:00:00`).getTime() -
          new Date(`${fromDate}T00:00:00`).getTime()) /
        86_400_000
      if (span > 90) {
        showErrorToast(
          t({
            zh: "时间范围最长 90 天。请缩短后再导出。",
            en: "The range can cover at most 90 days. Shorten it and try again.",
          }),
        )
        return
      }
    }
    if (mode === "self" && exportKind === "student_report_pdf") {
      if (!reportClassroomId) {
        showErrorToast(
          t({ zh: "请先选择课堂。", en: "Choose a classroom first." }),
        )
        return
      }
      if ((fromDate && !toDate) || (!fromDate && toDate)) {
        showErrorToast(
          t({
            zh: "自定义范围需要同时填写开始和结束日期。",
            en: "A custom range needs both a start and an end date.",
          }),
        )
        return
      }
      const report: ExportCreate = {
        kind: "student_report_pdf",
        scope: "self",
        classroom_id: reportClassroomId,
        group_by_item: false,
        confirm_contains_student_audio: false,
      }
      if (fromDate && toDate) {
        report.from = new Date(`${fromDate}T00:00:00`).toISOString()
        report.to = new Date(`${toDate}T23:59:59`).toISOString()
      } else {
        report.days = reportDays
      }
      createJob.mutate(report)
      return
    }
    if (mode === "classroom" && exportKind === "class_report_pdf") {
      if ((fromDate && !toDate) || (!fromDate && toDate)) {
        showErrorToast(
          t({
            zh: "自定义范围需要同时填写开始和结束日期。",
            en: "A custom range needs both a start and an end date.",
          }),
        )
        return
      }
      const report: ExportCreate = {
        kind: "class_report_pdf",
        scope: "classroom",
        classroom_id: classroomId,
        group_by_item: false,
        confirm_contains_student_audio: false,
      }
      if (fromDate && toDate) {
        report.from = new Date(`${fromDate}T00:00:00`).toISOString()
        report.to = new Date(`${toDate}T23:59:59`).toISOString()
      } else {
        report.days = reportDays
      }
      createJob.mutate(report)
      return
    }
    const body: ExportCreate = {
      scope: mode === "classroom" ? "classroom" : "self",
      group_by_item: mode === "classroom" ? groupByItem : false,
      confirm_contains_student_audio: confirmFlag,
    }
    if (fromDate) body.from = new Date(`${fromDate}T00:00:00`).toISOString()
    if (toDate) body.to = new Date(`${toDate}T23:59:59`).toISOString()
    if (mode === "classroom") {
      body.classroom_id = classroomId
      if (exerciseId) body.exercise_id = exerciseId
    }
    createJob.mutate(body)
  }

  const download = async (job: ExportJobPublic) => {
    try {
      await saveZip(job)
      refresh()
    } catch (error) {
      const detail = error instanceof Error ? error.message : "export_not_ready"
      showErrorToast(extractErrorMessage({ body: { detail } }))
    }
  }

  const rows = jobs.data?.data ?? []

  return (
    <div className="grid gap-6">
      <section className="rounded-2xl border border-border/70 bg-card p-4 sm:p-6">
        <h2 className="text-lg font-semibold">
          {mode === "classroom"
            ? t({ zh: "导出课堂录音", en: "Export classroom recordings" })
            : exportKind === "student_report_pdf"
              ? t({ zh: "导出我的学情报告", en: "Export my learning report" })
              : t({ zh: "导出我的录音", en: "Export my recordings" })}
        </h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          {mode === "classroom"
            ? t({
                zh: "打包本班学生仍留在服务器上的原始录音（不转码）。正在评分的不包含。默认最近 7 天，最长 90 天。超过 2GB 会直接拒绝，请缩小范围。文件保留 7 天。",
                en: "Pack original recordings still on the server (no re-encoding). In-progress scoring is left out. Default is the last 7 days, 90 days maximum. Over 2GB is rejected — narrow the range. Files stay for 7 days.",
              })
            : exportKind === "student_report_pdf"
              ? t({
                  zh: "生成你自己的学情报告 PDF（中文）。默认最近 90 天，自定义范围也不能超过 90 天。没有已出分练习时仍会生成一份空报告。分数是参考，不是官方成绩。文件保留 7 天。",
                  en: "Build a PDF of your own learning report. The default is the last 90 days, and a custom range cannot be longer. If nothing is scored yet, you still get an empty report. Scores are reference only, not an official result. Files stay for 7 days.",
                })
              : t({
                  zh: "只包含你自己的原始录音，正在评分的不会放进去。没有录音时不会生成空压缩包。文件保留 7 天。",
                  en: "Only your own original recordings are included. Scoring still in progress is left out. If there is nothing to pack, no empty file is created. Files stay for 7 days.",
                })}
        </p>
        {mode === "classroom" && (
          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              type="button"
              variant={exportKind === "audio_zip" ? "default" : "outline"}
              className="h-11"
              onClick={() => setExportKind("audio_zip")}
            >
              {t({ zh: "录音包", en: "Audio package" })}
            </Button>
            <Button
              type="button"
              variant={
                exportKind === "class_report_pdf" ? "default" : "outline"
              }
              className="h-11"
              onClick={() => setExportKind("class_report_pdf")}
            >
              {t({ zh: "班级报告 PDF", en: "Class report PDF" })}
            </Button>
          </div>
        )}
        {mode === "self" && (
          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              type="button"
              variant={exportKind === "audio_zip" ? "default" : "outline"}
              className="h-11"
              onClick={() => setExportKind("audio_zip")}
            >
              {t({ zh: "录音包", en: "Audio package" })}
            </Button>
            <Button
              type="button"
              variant={
                exportKind === "student_report_pdf" ? "default" : "outline"
              }
              className="h-11"
              onClick={() => setExportKind("student_report_pdf")}
            >
              {t({ zh: "学情报告 PDF", en: "Learning report PDF" })}
            </Button>
          </div>
        )}
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          {mode === "self" && exportKind === "student_report_pdf" && (
            <>
              <label className="grid gap-1.5 text-sm sm:col-span-2">
                <span className="font-medium">
                  {t({ zh: "课堂", en: "Classroom" })}
                </span>
                <select
                  className="h-11 rounded-md border border-input bg-background px-3 text-base"
                  value={reportClassroomId}
                  onChange={(event) => setReportClassroomId(event.target.value)}
                >
                  <option value="">
                    {t({ zh: "选择课堂", en: "Choose a classroom" })}
                  </option>
                  {(enrollments.data ?? []).map((room) => (
                    <option key={room.classroom_id} value={room.classroom_id}>
                      {room.name} · {room.code}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1.5 text-sm sm:col-span-2">
                <span className="font-medium">
                  {t({ zh: "最近天数", en: "Recent days" })}
                </span>
                <select
                  className="h-11 rounded-md border border-input bg-background px-3 text-base"
                  value={reportDays}
                  onChange={(event) =>
                    setReportDays(Number(event.target.value))
                  }
                >
                  <option value={7}>
                    {t({ zh: "最近 7 天", en: "Last 7 days" })}
                  </option>
                  <option value={30}>
                    {t({ zh: "最近 30 天", en: "Last 30 days" })}
                  </option>
                  <option value={90}>
                    {t({ zh: "最近 90 天", en: "Last 90 days" })}
                  </option>
                </select>
                <span className="text-muted-foreground">
                  {t({
                    zh: "如果下面填写了开始和结束日期，以日期为准，最长 90 天。",
                    en: "If you fill in both dates below, those dates are used instead. 90 days maximum.",
                  })}
                </span>
              </label>
            </>
          )}
          {mode === "classroom" && (
            <label className="grid gap-1.5 text-sm sm:col-span-2">
              <span className="font-medium">
                {t({ zh: "课堂", en: "Classroom" })}
              </span>
              <select
                className="h-11 rounded-md border border-input bg-background px-3 text-base"
                value={classroomId}
                onChange={(event) => {
                  setClassroomId(event.target.value)
                  setExerciseId("")
                }}
              >
                <option value="">
                  {t({ zh: "选择课堂", en: "Choose a classroom" })}
                </option>
                {(classrooms.data ?? []).map((room: ClassroomPublic) => (
                  <option key={room.id} value={room.id}>
                    {room.name} · {room.code}
                  </option>
                ))}
              </select>
            </label>
          )}
          {mode === "classroom" && exportKind === "audio_zip" && (
            <label className="grid gap-1.5 text-sm sm:col-span-2">
              <span className="font-medium">
                {t({ zh: "练习（可选）", en: "Exercise (optional)" })}
              </span>
              <select
                className="h-11 rounded-md border border-input bg-background px-3 text-base"
                value={exerciseId}
                onChange={(event) => setExerciseId(event.target.value)}
                disabled={!selected}
              >
                <option value="">
                  {t({
                    zh: "时间范围内的全部练习",
                    en: "All exercises in the date range",
                  })}
                </option>
                {(exercises.data ?? []).map(
                  (exercise: ClassroomExercisePublic) => (
                    <option key={exercise.id} value={exercise.id}>
                      {exercise.title}
                    </option>
                  ),
                )}
              </select>
            </label>
          )}
          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">
              {t({ zh: "开始日期", en: "From" })}
            </span>
            <input
              type="date"
              className="h-11 rounded-md border border-input bg-background px-3 text-base"
              value={fromDate}
              onChange={(event) => setFromDate(event.target.value)}
            />
          </label>
          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">
              {t({ zh: "结束日期", en: "To" })}
            </span>
            <input
              type="date"
              className="h-11 rounded-md border border-input bg-background px-3 text-base"
              value={toDate}
              onChange={(event) => setToDate(event.target.value)}
            />
          </label>
          {mode === "classroom" && exportKind === "audio_zip" && (
            <label
              htmlFor="group-by-item"
              className="flex min-h-11 items-center gap-3 text-sm sm:col-span-2"
            >
              <Checkbox
                id="group-by-item"
                checked={groupByItem}
                onCheckedChange={(value) => setGroupByItem(value === true)}
              />
              <span>
                {t({
                  zh: "按题目分文件夹",
                  en: "Group files by item",
                })}
              </span>
            </label>
          )}
        </div>
        <div className="mt-5">
          {mode === "classroom" ? (
            exportKind === "class_report_pdf" ? (
              <Button
                type="button"
                className="h-11"
                onClick={() => submit(true)}
                disabled={!classroomId || createJob.isPending}
              >
                {t({ zh: "导出班级报告", en: "Export class report" })}
              </Button>
            ) : (
              <Button
                type="button"
                className="h-11"
                onClick={() => {
                  setConfirmed(false)
                  setConfirmOpen(true)
                }}
                disabled={!classroomId || createJob.isPending}
              >
                {t({ zh: "导出录音", en: "Export recordings" })}
              </Button>
            )
          ) : (
            <LoadingButton
              type="button"
              className="h-11"
              loading={createJob.isPending}
              onClick={() => submit(false)}
            >
              {exportKind === "student_report_pdf"
                ? t({ zh: "生成学情报告", en: "Build learning report" })
                : t({ zh: "导出我的录音", en: "Export my recordings" })}
            </LoadingButton>
          )}
        </div>
      </section>

      <section className="grid gap-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">
            {t({ zh: "下载中心", en: "Download center" })}
            {(jobs.data?.unseen_ready ?? 0) > 0 && (
              <span className="ml-2 inline-flex min-h-6 min-w-6 items-center justify-center rounded-full bg-primary px-2 text-xs font-semibold text-primary-foreground">
                {jobs.data?.unseen_ready}
              </span>
            )}
          </h2>
          <Button
            type="button"
            variant="outline"
            className="h-11"
            onClick={() => void jobs.refetch()}
          >
            {t({ zh: "刷新", en: "Refresh" })}
          </Button>
        </div>
        {jobs.isPending ? (
          <p className="rounded-2xl border border-dashed p-6 text-sm text-muted-foreground">
            {t({ zh: "正在加载导出任务…", en: "Loading export jobs…" })}
          </p>
        ) : jobs.isError ? (
          <p className="rounded-2xl border border-destructive/30 bg-destructive/5 p-6 text-sm">
            {t({
              zh: "下载中心暂时打不开，请重试。",
              en: "The download center could not be loaded. Try again.",
            })}
          </p>
        ) : rows.length === 0 ? (
          <p className="rounded-2xl border border-dashed p-6 text-sm leading-6 text-muted-foreground">
            {mode === "self"
              ? t({
                  zh: "还没有导出任务。可以打包自己的录音，或生成学情报告 PDF。录音没有内容时不会生成空压缩包；学情报告没有已出分练习时仍会给出一份空报告。",
                  en: "No export jobs yet. You can pack your recordings or build a learning-report PDF. Audio with nothing to pack is not created; a report with no scored answers is still generated.",
                })
              : t({
                  zh: "还没有导出任务。选好范围后开始导出，完成后在这里下载。没有符合条件的录音时，不会生成空压缩包。",
                  en: "No export jobs yet. Choose a range and start one. Finished packages show up here. If nothing matches, no empty file is created.",
                })}
          </p>
        ) : (
          <ul className="grid gap-3">
            {rows.map((job) => {
              const expired = job.status === "expired" || isPast(job.expires_at)
              const ready = job.status === "succeeded" && !expired
              const pdf = isPdfJob(job)
              return (
                <li
                  key={job.id}
                  className="rounded-2xl border border-border/70 bg-card p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="break-all text-sm font-semibold">
                        <span className="mr-2 inline-flex min-h-6 items-center rounded-full bg-secondary px-2 text-xs font-medium">
                          {isClassReportJob(job)
                            ? t({ zh: "班级报告", en: "Class report" })
                            : pdf
                              ? t({ zh: "学情报告", en: "Report" })
                              : t({ zh: "录音包", en: "Audio" })}
                        </span>
                        {job.download_name || job.id}
                      </p>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {expired
                          ? t({ zh: "已过期", en: "Expired" })
                          : exportStatusLabel(job.status, t, job.kind)}
                        {job.status === "running" || job.status === "succeeded"
                          ? ` · ${job.progress}%`
                          : ""}
                        {pdf &&
                        job.status === "succeeded" &&
                        job.included_count > 0
                          ? t({
                              zh: ` · ${job.included_count} 条已出分作答`,
                              en: ` · ${job.included_count} scored answers`,
                            })
                          : pdf && job.status === "succeeded"
                            ? t({
                                zh: " · 本阶段暂无已出分作答",
                                en: " · no scored answers in this period",
                              })
                            : ""}
                        {!pdf && job.included_count > 0
                          ? t({
                              zh: ` · ${job.included_count} 条录音`,
                              en: ` · ${job.included_count} recordings`,
                            })
                          : ""}
                        {!pdf && job.missing_count > 0
                          ? t({
                              zh: ` · ${job.missing_count} 条缺失`,
                              en: ` · ${job.missing_count} missing`,
                            })
                          : ""}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {ready && (
                        <Button
                          type="button"
                          className="h-11"
                          onClick={() => void download(job)}
                        >
                          <Download className="size-4" />
                          {t({ zh: "下载", en: "Download" })}
                        </Button>
                      )}
                      {job.status === "failed" && (
                        <LoadingButton
                          type="button"
                          variant="outline"
                          className="h-11"
                          loading={retryJob.isPending}
                          onClick={() => retryJob.mutate(job.id)}
                        >
                          <RefreshCw className="size-4" />
                          {t({ zh: "重试", en: "Retry" })}
                        </LoadingButton>
                      )}
                    </div>
                  </div>
                  {(job.status === "queued" || job.status === "running") && (
                    <div
                      className="mt-3 h-2 overflow-hidden rounded-full bg-muted"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={job.progress}
                      role="progressbar"
                    >
                      <div
                        className={cn(
                          "h-full bg-primary transition-[width]",
                          job.status === "queued" && "w-1/12",
                        )}
                        style={
                          job.status === "running"
                            ? { width: `${Math.max(job.progress, 8)}%` }
                            : undefined
                        }
                      />
                    </div>
                  )}
                  {job.status === "failed" && (
                    <p className="mt-3 text-sm leading-6 text-destructive">
                      {exportJobMessage(job.error, t)}
                    </p>
                  )}
                  {expired && job.status !== "failed" && (
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">
                      {pdf
                        ? t({
                            zh: "这份学情报告已超过保留期，文件已清理。需要的话请重新导出。",
                            en: "This learning report has passed its retention window and the file was removed. Export it again if you still need it.",
                          })
                        : t({
                            zh: "这个录音包已超过保留期，文件已清理。需要的话请重新导出。",
                            en: "This package has passed its retention window and the file was removed. Export it again if you still need it.",
                          })}
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t({
                zh: "确认导出学生原始录音",
                en: "Confirm student audio export",
              })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "压缩包里是学生的原始口语录音，仅供本班教学使用。请确认你是该课堂的授权教师。",
                en: "The package contains students' original speaking recordings and is for this class's teaching only. Confirm you are the authorized teacher.",
              })}
            </DialogDescription>
          </DialogHeader>
          <label
            htmlFor="confirm-student-audio"
            className="flex min-h-11 items-start gap-3 text-sm leading-6"
          >
            <Checkbox
              id="confirm-student-audio"
              className="mt-1"
              checked={confirmed}
              onCheckedChange={(value) => setConfirmed(value === true)}
            />
            <span>
              {t({
                zh: "我确认此压缩包包含学生原始音频，并只用于教学。",
                en: "I confirm this package contains students' original audio and is for teaching only.",
              })}
            </span>
          </label>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              className="h-11"
              onClick={() => setConfirmOpen(false)}
            >
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <LoadingButton
              type="button"
              className="h-11"
              loading={createJob.isPending}
              disabled={!confirmed}
              onClick={() => submit(true)}
            >
              {t({ zh: "确认并导出", en: "Confirm and export" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
