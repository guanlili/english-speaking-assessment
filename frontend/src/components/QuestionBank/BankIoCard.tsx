/**
 * 题库批量导入导出入口卡片：下载模板 / 批量导入 / 导出题目。
 * 挂在题目库页顶部，普通教师即可使用（后端 TeacherUserDep 同权限）。
 */
import { useState } from "react"

import { QuestionBankService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import {
  extractDownloadErrorDetail,
  localizeQuestionBankDetail,
} from "@/lib/questionImport"
import { QuestionBankExportDialog } from "./ExportDialog"
import { QuestionBankImportDialog } from "./ImportDialog"

export function QuestionBankIoCard() {
  const { t } = useI18n()
  const { showErrorToast } = useCustomToast()
  const [importOpen, setImportOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [downloading, setDownloading] = useState(false)

  const downloadTemplate = async (format: "xlsx" | "csv") => {
    setDownloading(true)
    try {
      const blob = await QuestionBankService.downloadImportTemplate({ format })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      document.body.append(anchor)
      anchor.href = url
      anchor.download = `question-bank-import-template.${format}`
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      showErrorToast(
        t(localizeQuestionBankDetail(await extractDownloadErrorDetail(err))),
      )
    } finally {
      setDownloading(false)
    }
  }

  return (
    <section
      aria-label={t({ zh: "批量导入导出", en: "Bulk import & export" })}
      className="rounded-2xl border border-primary/10 bg-card p-4 shadow-sm sm:p-6"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-primary">
            {t({
              zh: "批量录入 · 备份 · 交换",
              en: "Bulk entry · Backup · Share",
            })}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t({
              zh: "下载模板批量录入题目，先预览再导入；导入的题目直接进入下方题库，可搜索、选题、发布。",
              en: "Download a template to enter questions in bulk, preview, then import. Imported items land in the bank below, ready to search, select and publish.",
            })}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="secondary"
                className="min-h-11"
                disabled={downloading}
              >
                {t({ zh: "下载模板", en: "Download template" })}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                className="min-h-11 text-base"
                onSelect={() => void downloadTemplate("xlsx")}
              >
                {t({
                  zh: "Excel（按题型分工作表，带下拉）",
                  en: "Excel (sheet per type, dropdowns)",
                })}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="min-h-11 text-base"
                onSelect={() => void downloadTemplate("csv")}
              >
                {t({
                  zh: "CSV（单文件，题型列）",
                  en: "CSV (single file, type column)",
                })}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button className="min-h-11" onClick={() => setImportOpen(true)}>
            {t({ zh: "批量导入", en: "Bulk import" })}
          </Button>
          <Button
            variant="secondary"
            className="min-h-11"
            onClick={() => setExportOpen(true)}
          >
            {t({ zh: "导出题目", en: "Export questions" })}
          </Button>
        </div>
      </div>
      <QuestionBankImportDialog
        open={importOpen}
        onOpenChange={setImportOpen}
      />
      <QuestionBankExportDialog
        open={exportOpen}
        onOpenChange={setExportOpen}
      />
    </section>
  )
}
