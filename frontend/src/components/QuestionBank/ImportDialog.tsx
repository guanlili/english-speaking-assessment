/**
 * 题库批量导入弹窗：选文件 → 预览（计数/问题行/疑似重复）→ 确认导入。
 *
 * 预览不落库；确认时重新上传同一文件由后端重新校验（预览与确认之间
 * 题库变化不会产生脏数据）。文件一旦变化预览即作废（vocablevels 模式）。
 */

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef, useState } from "react"
import type {
  QuestionBankImportPreview,
  QuestionBankImportResult,
} from "@/client"
import { ApiError, QuestionBankService } from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import {
  localizeQuestionBankDetail,
  localizeQuestionImportIssue,
  questionBankTypeLabel,
} from "@/lib/questionImport"
import { extractErrorMessage } from "@/utils"

const MAX_FILE_MB = 5

function issueText(
  t: (v: { zh: string; en: string }) => string,
  issue: { type: string; line: number; reason: string },
): string {
  const reason = t(localizeQuestionImportIssue(issue.reason))
  if (issue.type === "-") {
    return t({
      zh: `第 ${issue.line} 行 · ${reason}`,
      en: `Line ${issue.line} · ${reason}`,
    })
  }
  const typeLabel = t(questionBankTypeLabel(issue.type))
  return t({
    zh: `${typeLabel} · 第 ${issue.line} 行 · ${reason}`,
    en: `${typeLabel} · line ${issue.line} · ${reason}`,
  })
}

export function QuestionBankImportDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<QuestionBankImportPreview | null>(null)
  const [includeSuspected, setIncludeSuspected] = useState(false)
  const [result, setResult] = useState<QuestionBankImportResult | null>(null)

  const reset = () => {
    setFile(null)
    setPreview(null)
    setResult(null)
    setIncludeSuspected(false)
  }

  const previewMutation = useMutation({
    mutationFn: (target: File) =>
      QuestionBankService.questionBankImportPreview({
        formData: { file: target as unknown as string },
      }),
    onSuccess: (data) => {
      setPreview(data)
      setResult(null)
    },
    onError: (err) =>
      showErrorToast(t(localizeQuestionBankDetail(extractErrorMessage(err)))),
  })

  const confirmMutation = useMutation({
    mutationFn: (args: { target: File; include: boolean }) =>
      QuestionBankService.questionBankImportConfirm({
        formData: {
          file: args.target as unknown as string,
          include_suspected: args.include,
        },
      }),
    onSuccess: (data) => {
      setResult(data)
      setPreview(null)
      showSuccessToast(
        t({
          zh: `已导入 ${data.sheets.reduce((sum, s) => sum + s.created, 0)} 道题`,
          en: `Imported ${data.sheets.reduce((sum, s) => sum + s.created, 0)} items`,
        }),
      )
      // 导入的数据落在现有四表：刷新题库相关查询，组卷/搜索立刻可见
      for (const key of [
        ["admin", "passages"],
        ["admin", "sentences"],
        ["admin", "question-bank"],
        ["admin", "scenarios"],
        ["admin", "instructions"],
        ["admin", "topics"],
      ]) {
        void queryClient.invalidateQueries({ queryKey: key })
      }
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        showErrorToast(t(localizeQuestionBankDetail(extractErrorMessage(err))))
      } else {
        showErrorToast(
          t({ zh: "导入失败，请重试", en: "Import failed, please retry" }),
        )
      }
    },
  })

  const pickFile = (picked: File | null | undefined) => {
    if (!picked) return
    if (picked.size > MAX_FILE_MB * 1024 * 1024) {
      showErrorToast(
        t({
          zh: `文件超过 ${MAX_FILE_MB}MB 上限`,
          en: `File exceeds the ${MAX_FILE_MB}MB limit`,
        }),
      )
      return
    }
    if (!/\.(xlsx|csv)$/i.test(picked.name)) {
      showErrorToast(
        t({
          zh: "仅支持 .xlsx 或 .csv 文件",
          en: "Only .xlsx or .csv files are supported",
        }),
      )
      return
    }
    setFile(picked)
    setPreview(null)
    setResult(null)
  }

  const suspectedTotal =
    preview?.sheets.reduce((sum, s) => sum + s.suspected_duplicate_count, 0) ??
    0
  const effectiveValid =
    (preview?.total_valid ?? 0) + (includeSuspected ? suspectedTotal : 0)
  const busy = previewMutation.isPending || confirmMutation.isPending

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset()
        onOpenChange(next)
      }}
    >
      <DialogContent className="max-h-[85svh] gap-4 overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {t({ zh: "批量导入题目", en: "Bulk import questions" })}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "上传填好的 Excel/CSV 模板：先预览，确认无误再导入。导入不会修改已有题目。",
              en: "Upload your filled Excel/CSV template: preview first, then confirm. Import never modifies existing questions.",
            })}
          </DialogDescription>
        </DialogHeader>

        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,.csv"
          className="hidden"
          onChange={(event) => {
            pickFile(event.target.files?.[0])
            event.target.value = ""
          }}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            className="min-h-11"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
          >
            {t({ zh: "选择文件", en: "Choose file" })}
          </Button>
          {file && (
            <span className="min-h-11 content-center text-sm text-muted-foreground">
              {file.name}
            </span>
          )}
          {file && !result && (
            <Button
              className="min-h-11"
              onClick={() => previewMutation.mutate(file)}
              disabled={busy}
            >
              {t({ zh: "预览", en: "Preview" })}
            </Button>
          )}
        </div>

        {preview && (
          <div className="space-y-3 rounded-xl border border-primary/10 bg-secondary/40 p-4 text-sm">
            {preview.sheets.length === 0 ? (
              <p className="text-muted-foreground">
                {t({
                  zh: "文件中没有可导入的数据行。",
                  en: "No importable data rows in this file.",
                })}
              </p>
            ) : (
              <ul className="space-y-1.5">
                {preview.sheets.map((sheet) => (
                  <li
                    key={sheet.type}
                    className="flex flex-wrap items-center gap-2"
                  >
                    <span className="font-medium">
                      {t(questionBankTypeLabel(sheet.type))}
                    </span>
                    <span className="text-primary">
                      {t({
                        zh: `将导入 ${sheet.valid_count}`,
                        en: `${sheet.valid_count} to import`,
                      })}
                    </span>
                    {sheet.exact_duplicate_count > 0 && (
                      <span className="text-muted-foreground">
                        {t({
                          zh: `完全重复 ${sheet.exact_duplicate_count}（自动跳过）`,
                          en: `${sheet.exact_duplicate_count} exact duplicates (skipped)`,
                        })}
                      </span>
                    )}
                    {sheet.suspected_duplicate_count > 0 && (
                      <span className="text-amber-600 dark:text-amber-400">
                        {t({
                          zh: `疑似重复 ${sheet.suspected_duplicate_count}`,
                          en: `${sheet.suspected_duplicate_count} possible duplicates`,
                        })}
                      </span>
                    )}
                    {sheet.missing_audio_count > 0 && (
                      <span className="text-muted-foreground">
                        {t({
                          zh: `缺音频 ${sheet.missing_audio_count}`,
                          en: `${sheet.missing_audio_count} missing audio`,
                        })}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {preview.new_topics.length > 0 && (
              <p className="text-muted-foreground">
                {t({
                  zh: `将自动新建问答主题：${preview.new_topics.join("、")}`,
                  en: `New Q&A topics to create: ${preview.new_topics.join(", ")}`,
                })}
              </p>
            )}
            {preview.unit_fallback_count > 0 && (
              <p className="text-muted-foreground">
                {t({
                  zh: `${preview.unit_fallback_count} 个篇目的单元未匹配，将按无单元导入（主题列生效）`,
                  en: `${preview.unit_fallback_count} passage(s) had no matching unit; they import without a unit (topic column applies)`,
                })}
              </p>
            )}
            {preview.standalone_sentence_count > 0 && (
              <p className="text-muted-foreground">
                {t({
                  zh: `${preview.standalone_sentence_count} 个句子挂靠的篇目未找到，将作为独立句导入`,
                  en: `${preview.standalone_sentence_count} sentence(s) had no matching passage; they import as standalone items`,
                })}
              </p>
            )}

            {preview.suspected.length > 0 && (
              <div>
                <p className="font-medium text-amber-600 dark:text-amber-400">
                  {t({
                    zh: "疑似重复（默认不导入）",
                    en: "Possible duplicates (excluded by default)",
                  })}
                </p>
                <ul className="mt-1 max-h-32 space-y-1 overflow-y-auto text-xs text-muted-foreground">
                  {preview.suspected.map((issue, index) => (
                    <li key={`${issue.type}-${issue.line}-${index}`}>
                      {issueText(t, issue)}
                    </li>
                  ))}
                </ul>
                {preview.suspected_truncated && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t({ zh: "仅显示前 100 条", en: "First 100 shown" })}
                  </p>
                )}
                <div className="mt-2 flex items-center gap-2">
                  <Checkbox
                    id="include-suspected"
                    checked={includeSuspected}
                    onCheckedChange={(checked) =>
                      setIncludeSuspected(checked === true)
                    }
                  />
                  <Label htmlFor="include-suspected" className="text-sm">
                    {t({
                      zh: `仍导入疑似重复（${suspectedTotal} 行）`,
                      en: `Import possible duplicates anyway (${suspectedTotal} rows)`,
                    })}
                  </Label>
                </div>
              </div>
            )}

            {preview.issues.length > 0 && (
              <div>
                <p className="font-medium text-destructive">
                  {t({
                    zh: "错误行（不会导入）",
                    en: "Invalid rows (will not import)",
                  })}
                </p>
                <ul className="mt-1 max-h-32 space-y-1 overflow-y-auto text-xs text-muted-foreground">
                  {preview.issues.map((issue, index) => (
                    <li key={`${issue.type}-${issue.line}-${index}`}>
                      {issueText(t, issue)}
                    </li>
                  ))}
                </ul>
                {preview.issues_truncated && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t({ zh: "仅显示前 200 条", en: "First 200 shown" })}
                  </p>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Button
                className="min-h-11"
                disabled={busy || effectiveValid === 0}
                onClick={() =>
                  file &&
                  confirmMutation.mutate({
                    target: file,
                    include: includeSuspected,
                  })
                }
              >
                {t({ zh: "确认导入", en: "Confirm import" })}
              </Button>
              {effectiveValid === 0 && (
                <span className="text-sm text-muted-foreground">
                  {t({
                    zh: "没有新题可导入（重复或错误行已全部排除）",
                    en: "Nothing new to import (duplicates and invalid rows excluded)",
                  })}
                </span>
              )}
            </div>
          </div>
        )}

        {result && (
          <div className="space-y-3 rounded-xl border border-primary/10 bg-secondary/40 p-4 text-sm">
            <ul className="space-y-1.5">
              {result.sheets.map((sheet) => (
                <li
                  key={sheet.type}
                  className="flex flex-wrap items-center gap-2"
                >
                  <span className="font-medium">
                    {t(questionBankTypeLabel(sheet.type))}
                  </span>
                  <span className="text-primary">
                    {t({
                      zh: `新建 ${sheet.created}`,
                      en: `${sheet.created} created`,
                    })}
                  </span>
                  {sheet.skipped_duplicate > 0 && (
                    <span className="text-muted-foreground">
                      {t({
                        zh: `跳过重复 ${sheet.skipped_duplicate}`,
                        en: `${sheet.skipped_duplicate} duplicates skipped`,
                      })}
                    </span>
                  )}
                  {sheet.skipped_suspected > 0 && (
                    <span className="text-muted-foreground">
                      {t({
                        zh: `排除疑似重复 ${sheet.skipped_suspected}`,
                        en: `${sheet.skipped_suspected} possible duplicates excluded`,
                      })}
                    </span>
                  )}
                  {sheet.skipped_invalid > 0 && (
                    <span className="text-destructive">
                      {t({
                        zh: `错误行 ${sheet.skipped_invalid}`,
                        en: `${sheet.skipped_invalid} invalid rows`,
                      })}
                    </span>
                  )}
                </li>
              ))}
            </ul>
            {result.created_topics.length > 0 && (
              <p className="text-muted-foreground">
                {t({
                  zh: `已新建问答主题：${result.created_topics.join("、")}`,
                  en: `Q&A topics created: ${result.created_topics.join(", ")}`,
                })}
              </p>
            )}
            {result.missing_audio_total > 0 && (
              <p className="text-amber-600 dark:text-amber-400">
                {t({
                  zh: `有 ${result.missing_audio_total} 道题缺音频：请到题目编辑里上传或生成，未配齐前不宜用于自动考试。`,
                  en: `${result.missing_audio_total} item(s) have no audio yet: upload or generate it in the question editor before using them in automated exams.`,
                })}
              </p>
            )}
            {result.issues.length > 0 && (
              <ul className="max-h-32 space-y-1 overflow-y-auto text-xs text-muted-foreground">
                {result.issues.map((issue, index) => (
                  <li key={`${issue.type}-${issue.line}-${index}`}>
                    {issueText(t, issue)}
                  </li>
                ))}
              </ul>
            )}
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" className="min-h-11" onClick={reset}>
                {t({ zh: "继续导入下一批", en: "Import another batch" })}
              </Button>
              <Button className="min-h-11" onClick={() => onOpenChange(false)}>
                {t({ zh: "完成", en: "Done" })}
              </Button>
            </div>
          </div>
        )}
        <p className="text-xs leading-5 text-muted-foreground">
          {t({
            zh: "上限：2000 行 / 5MB。完全重复自动跳过；修改旧题请到各题型的编辑入口。",
            en: "Limits: 2000 rows / 5MB. Exact duplicates are skipped; edit existing questions in each section.",
          })}
        </p>
      </DialogContent>
    </Dialog>
  )
}
