/**
 * 题库批量导出弹窗：按题型/主题/考试题型/级别/关键词筛选，导出与导入
 * 模板同构的 xlsx（分工作表）或 CSV（题型列）——导出文件可直接再次导入。
 */

import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { AdminService, QuestionBankService } from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { localDateStamp } from "@/lib/dates"
import { useI18n } from "@/lib/i18n"
import { questionBankErrorMessage } from "@/lib/questionImport"
import {
  EXAM_KIND_LABELS,
  ITEM_TYPE_LABELS,
  VOCAB_LEVEL_LABELS,
  VOCAB_LEVEL_ORDER,
} from "@/lib/terms"

const ALL = "__all__"

export function QuestionBankExportDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useI18n()
  const { showErrorToast } = useCustomToast()
  const [types, setTypes] = useState<string[]>([
    "passage",
    "repeat",
    "question",
    "instruction",
  ])
  const [topic, setTopic] = useState<string>(ALL)
  const [examKind, setExamKind] = useState<string>(ALL)
  const [examLevel, setExamLevel] = useState<string>(ALL)
  const [keyword, setKeyword] = useState("")
  const [format, setFormat] = useState<"xlsx" | "csv">("xlsx")
  const [downloading, setDownloading] = useState(false)

  const topicsQuery = useQuery({
    queryKey: ["admin", "topics"],
    queryFn: () => AdminService.listTopics(),
  })

  const toggleType = (type: string, checked: boolean) => {
    setTypes((prev) =>
      checked
        ? [...new Set([...prev, type])]
        : prev.filter((item) => item !== type),
    )
  }

  const download = async () => {
    setDownloading(true)
    try {
      const blob = await QuestionBankService.exportQuestionBank({
        types,
        topic: topic === ALL ? undefined : topic,
        examKind: examKind === ALL ? undefined : examKind,
        examLevel: examLevel === ALL ? undefined : examLevel,
        q: keyword.trim() || undefined,
        format,
      })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      document.body.append(anchor)
      anchor.href = url
      anchor.download = `question-bank-export-${localDateStamp()}.${format}`
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      showErrorToast(t(await questionBankErrorMessage(err)))
    } finally {
      setDownloading(false)
    }
  }

  const selectClass =
    "h-11 rounded-xl border border-input bg-card px-3 text-base"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85svh] gap-4 overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {t({ zh: "导出题目", en: "Export questions" })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "按条件筛选导出；导出文件与导入模板同格式，整理后可重新导入。",
              en: "Filter and export; the file matches the import template and can be re-imported after editing.",
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label className="text-sm">
              {t({ zh: "题型（可多选）", en: "Question types (multi-select)" })}
            </Label>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {Object.entries(ITEM_TYPE_LABELS).map(([type, label]) => (
                <div
                  key={type}
                  className="flex min-h-11 items-center gap-2 text-sm"
                >
                  <Checkbox
                    id={`export-type-${type}`}
                    checked={types.includes(type)}
                    onCheckedChange={(checked) =>
                      toggleType(type, checked === true)
                    }
                  />
                  <label htmlFor={`export-type-${type}`} className="text-sm">
                    {t(label)}
                  </label>
                </div>
              ))}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="export-topic" className="text-sm">
                {t({ zh: "主题", en: "Topic" })}
              </Label>
              <Select value={topic} onValueChange={setTopic}>
                <SelectTrigger id="export-topic" className={selectClass}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL} className="min-h-11">
                    {t({ zh: "全部主题", en: "All topics" })}
                  </SelectItem>
                  {(topicsQuery.data ?? []).map((item) => (
                    <SelectItem key={item} value={item} className="min-h-11">
                      {item}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="export-kind" className="text-sm">
                {t({ zh: "考试题型", en: "Exam type" })}
              </Label>
              <Select value={examKind} onValueChange={setExamKind}>
                <SelectTrigger id="export-kind" className={selectClass}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL} className="min-h-11">
                    {t({ zh: "不限", en: "Any" })}
                  </SelectItem>
                  {Object.entries(EXAM_KIND_LABELS).map(([kind, label]) => (
                    <SelectItem key={kind} value={kind} className="min-h-11">
                      {t(label)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="export-level" className="text-sm">
                {t({ zh: "考试级别", en: "Exam level" })}
              </Label>
              <Select value={examLevel} onValueChange={setExamLevel}>
                <SelectTrigger id="export-level" className={selectClass}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL} className="min-h-11">
                    {t({ zh: "不限", en: "Any" })}
                  </SelectItem>
                  {VOCAB_LEVEL_ORDER.map((level) => (
                    <SelectItem key={level} value={level} className="min-h-11">
                      {t(VOCAB_LEVEL_LABELS[level])}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="export-format" className="text-sm">
                {t({ zh: "格式", en: "Format" })}
              </Label>
              <Select
                value={format}
                onValueChange={(value: string) =>
                  setFormat(value === "csv" ? "csv" : "xlsx")
                }
              >
                <SelectTrigger id="export-format" className={selectClass}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="xlsx" className="min-h-11">
                    {t({
                      zh: "Excel（分工作表）",
                      en: "Excel (sheets per type)",
                    })}
                  </SelectItem>
                  <SelectItem value="csv" className="min-h-11">
                    {t({ zh: "CSV（题型列）", en: "CSV (type column)" })}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="export-q" className="text-sm">
              {t({
                zh: "关键词（篇目标题/主题、问答题目/中文提示）",
                en: "Keyword (passage title/topic, question text/hint)",
              })}
            </Label>
            <Input
              id="export-q"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              className="min-h-11 text-base"
              placeholder={t({
                zh: "留空导出全部匹配项",
                en: "Leave empty to export all matches",
              })}
            />
          </div>

          <Button
            className="min-h-11 w-full"
            disabled={downloading || types.length === 0}
            onClick={() => void download()}
          >
            {downloading
              ? t({ zh: "生成中…", en: "Generating…" })
              : t({ zh: "导出", en: "Export" })}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
