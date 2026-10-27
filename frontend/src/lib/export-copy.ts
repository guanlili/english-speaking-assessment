import type { useI18n } from "@/lib/i18n"

type T = ReturnType<typeof useI18n>["t"]

/** 导出任务 error 字段（稳定码或短失败消息）→ 双语展示。 */
export function exportJobMessage(
  error: string | null | undefined,
  t: T,
): string {
  if (!error) {
    return t({
      zh: "没有可下载的录音包。",
      en: "There is no audio package to download.",
    })
  }
  if (error === "export_empty") {
    return t({
      zh: "这个范围内没有可导出的录音。换一个时间或练习后再试。",
      en: "No recordings in this range. Try a different time or exercise.",
    })
  }
  if (error === "export_all_missing") {
    return t({
      zh: "录音文件已经不在磁盘上（可能已过保留期），没有生成压缩包。",
      en: "The audio files are no longer on disk, so no package was created.",
    })
  }
  if (error === "export_too_large") {
    return t({
      zh: "预计体积超过 2GB。请缩小时间范围或练习范围后再导出。",
      en: "The estimated size is over 2GB. Narrow the dates or exercise and try again.",
    })
  }
  if (error === "export_pdf_too_large") {
    return t({
      zh: "学情报告文件超过 20MB，没有保存。请缩短时间范围后再试。",
      en: "The learning report was over 20MB and was not saved. Shorten the range and try again.",
    })
  }
  if (
    error === "export_report_forbidden" ||
    error === "export_report_student_only"
  ) {
    return t({
      zh: "学情报告只能由学生导出自己的记录。",
      en: "A learning report can only be exported by the student it belongs to.",
    })
  }
  if (error.startsWith("export_failed")) {
    return t({
      zh: `打包失败：${error}`,
      en: `Export failed: ${error}`,
    })
  }
  return error
}

export function exportStatusLabel(status: string, t: T, kind?: string): string {
  if (status === "queued") return t({ zh: "排队中", en: "Queued" })
  if (status === "running") {
    return kind === "student_report_pdf"
      ? t({ zh: "生成中", en: "Building" })
      : t({ zh: "打包中", en: "Packing" })
  }
  if (status === "succeeded") return t({ zh: "可以下载", en: "Ready" })
  if (status === "failed") return t({ zh: "未生成", en: "Not created" })
  if (status === "expired") return t({ zh: "已过期", en: "Expired" })
  return status
}
