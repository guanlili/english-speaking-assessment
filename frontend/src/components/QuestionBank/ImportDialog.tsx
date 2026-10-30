/**
 * 题库批量导入弹窗：选文件 → 预览（计数/错误行/疑似逐条对照）→ 确认导入 →
 * 本批直达使用（查看本批 / 带入组卷 / 补齐音频）。
 *
 * 逐条确认：疑似项展示「待导入 vs 已有候选」关键字段差异，默认跳过、可
 * 逐条或批量勾选导入；选择绑定当前文件的 (type:line)，换文件即清空。确认
 * 由后端在锁内重查对账——选择过期（422）或并发冲突（409）都会提示重新
 * 预览，绝不沿用旧选择静默导入。
 *
 * 竞态守卫：预览请求带 epoch，弹窗关闭/换文件后到达的迟到响应直接丢弃，
 * 不能恢复旧状态。
 */

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useRef, useState } from "react"
import type {
  QuestionBankCreatedItem,
  QuestionBankImportPreview,
  QuestionBankImportResult,
} from "@/client"
import { QuestionBankService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import {
  COMPOSER_PRESET_KEY,
  diffFieldLabel,
  localizeQuestionImportIssue,
  questionBankErrorMessage,
  questionBankTypeLabel,
} from "@/lib/questionImport"

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

function downloadBlob(blob: Blob | File, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  document.body.append(anchor)
  anchor.href = url
  anchor.download = filename
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/** 疑似对照：两侧快照逐字段并排，差异字段高亮。 */
function DiffTable({
  incoming,
  existing,
}: {
  incoming: Record<string, string>
  existing: Record<string, string>
}) {
  const { t } = useI18n()
  // 后端给的是完整值（与指纹同源）；长文本默认两行截断、可展开看全文——
  // 差异只在尾部时截断展示会「看起来完全相同」（评审 P2）
  const [expanded, setExpanded] = useState(false)
  const keys = Array.from(
    new Set([...Object.keys(incoming), ...Object.keys(existing)]),
  )
  const cellClass = expanded
    ? "whitespace-pre-wrap break-all"
    : "line-clamp-2 break-all"
  return (
    <div className="space-y-1">
      <div className="grid grid-cols-[auto_1fr_1fr] gap-x-2 gap-y-1 text-xs">
        <span />
        <span className="font-medium text-primary">
          {t({ zh: "待导入", en: "Incoming" })}
        </span>
        <span className="font-medium text-muted-foreground">
          {t({ zh: "已有候选", en: "Existing" })}
        </span>
        {keys.map((key) => {
          const differs = (incoming[key] ?? "") !== (existing[key] ?? "")
          return (
            <div key={key} className="col-span-3 grid grid-cols-subgrid">
              <span className="text-muted-foreground">
                {t(diffFieldLabel(key))}
              </span>
              <span
                className={`${cellClass} ${differs ? "rounded bg-amber-100 px-1 dark:bg-amber-900/40" : ""}`}
              >
                {incoming[key] || "—"}
              </span>
              <span
                className={`${cellClass} text-muted-foreground ${differs ? "rounded bg-amber-100 px-1 dark:bg-amber-900/40" : ""}`}
              >
                {existing[key] || "—"}
              </span>
            </div>
          )
        })}
      </div>
      <button
        type="button"
        className="-mx-1 flex min-h-11 items-center px-1 text-xs text-primary underline-offset-2 hover:underline"
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded
          ? t({ zh: "收起长文本", en: "Collapse long text" })
          : t({ zh: "展开完整内容", en: "Show full values" })}
      </button>
    </div>
  )
}

export function QuestionBankImportDialog({
  open,
  onOpenChange,
  classroom,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  classroom?: string
}) {
  const { t } = useI18n()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)
  /** 竞态守卫：每次重置/换文件自增；迟到的预览响应因 epoch 不匹配被丢弃 */
  const epochRef = useRef(0)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<QuestionBankImportPreview | null>(null)
  /** key = `${type}:${line}`，值为 true 表示勾选导入；缺省（不含 key）= 跳过 */
  const [decisions, setDecisions] = useState<Record<string, boolean>>({})
  const [result, setResult] = useState<QuestionBankImportResult | null>(null)
  /** 当前预览的指纹（与 preview 同生共死）：确认时带回后端锁内比对 */
  const [fingerprint, setFingerprint] = useState("")
  const [showBatch, setShowBatch] = useState(false)
  const [showAudioFix, setShowAudioFix] = useState(false)

  const reset = () => {
    epochRef.current += 1
    setFile(null)
    setPreview(null)
    setResult(null)
    setDecisions({})
    setFingerprint("")
    setShowBatch(false)
    setShowAudioFix(false)
  }

  const invalidateBank = () => {
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
  }

  const previewMutation = useMutation({
    mutationFn: (args: { target: File; epoch: number }) =>
      QuestionBankService.questionBankImportPreview({
        bodyQuestionBankQuestionBankImportPreview: { file: args.target },
      }).then((data) => ({ data, epoch: args.epoch })),
    onSuccess: ({ data, epoch }) => {
      if (epoch !== epochRef.current) {
        return // 迟到响应：弹窗已关/文件已换，丢弃
      }
      setPreview(data)
      setFingerprint(data.fingerprint ?? "")
      setResult(null)
    },
    onError: (err) => {
      void questionBankErrorMessage(err).then((msg) => showErrorToast(t(msg)))
    },
  })

  const confirmMutation = useMutation({
    mutationFn: (args: {
      target: File
      includeLines: string
      fingerprint: string
    }) =>
      QuestionBankService.questionBankImportConfirm({
        bodyQuestionBankQuestionBankImportConfirm: {
          file: args.target,
          include_lines: args.includeLines,
          preview_fingerprint: args.fingerprint,
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
      invalidateBank()
    },
    onError: (err) => {
      void questionBankErrorMessage(err).then((msg) => showErrorToast(t(msg)))
    },
  })

  const fixFileMutation = useMutation({
    mutationFn: (target: File) =>
      QuestionBankService.questionBankImportErrorFile(
        {
          bodyQuestionBankQuestionBankImportErrorFile: { file: target },
        },
        // xlsx/csv 二进制响应（0.99 迁移：fetch 客户端按调用点声明 parseAs）
        { parseAs: "blob" },
      ),
    onSuccess: (blob, target) => {
      downloadBlob(
        blob,
        `question-bank-fix.${target.name.toLowerCase().endsWith(".xlsx") ? "xlsx" : "csv"}`,
      )
    },
    onError: (err) => {
      void questionBankErrorMessage(err).then((msg) => showErrorToast(t(msg)))
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
    epochRef.current += 1
    setFile(picked)
    setPreview(null)
    setResult(null)
    setFingerprint("")
    // 疑似选择只对当前文件有效：换文件回到默认全部跳过
    setDecisions({})
    setShowBatch(false)
    setShowAudioFix(false)
  }

  const suspectedTotal =
    preview?.sheets.reduce((sum, s) => sum + s.suspected_duplicate_count, 0) ??
    0
  // invalid_total 含解析期（题型列无效）错误行——全无效文件也要有下载入口
  const invalidTotal = preview?.invalid_total ?? 0
  const selectedCount = Object.values(decisions).filter(Boolean).length
  const effectiveValid = (preview?.total_valid ?? 0) + selectedCount
  const busy =
    previewMutation.isPending ||
    confirmMutation.isPending ||
    fixFileMutation.isPending

  const confirmImport = () => {
    if (!file) return
    const includeLines = Object.entries(decisions)
      .filter(([, checked]) => checked)
      .map(([key]) => key)
      .join(",")
    confirmMutation.mutate({ target: file, includeLines, fingerprint })
  }

  /** 本批新建 → 组卷预选（一次性 sessionStorage 交接；老师检查后自行发布） */
  const sendToComposer = (items: QuestionBankCreatedItem[]) => {
    const preset = {
      passages: items.filter((i) => i.type === "passage").map((i) => i.id),
      sentences: items.filter((i) => i.type === "repeat").map((i) => i.id),
      questions: items.filter((i) => i.type === "question").map((i) => i.id),
      instructions: items
        .filter((i) => i.type === "instruction")
        .map((i) => i.id),
    }
    sessionStorage.setItem(COMPOSER_PRESET_KEY, JSON.stringify(preset))
    if (classroom) {
      void navigate({ to: "/t/$code", params: { code: classroom } })
    } else {
      void navigate({ to: "/classrooms" })
    }
  }

  const createdItems = result?.created_items ?? []
  const audioFixItems = createdItems.filter(
    (i) => i.needs_audio && i.audio_missing,
  )

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
              onClick={() =>
                file &&
                previewMutation.mutate({
                  target: file,
                  epoch: epochRef.current,
                })
              }
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
                    {(sheet.invalid_count ?? 0) > 0 && (
                      <span className="text-destructive">
                        {t({
                          zh: `错误行 ${sheet.invalid_count}`,
                          en: `${sheet.invalid_count} invalid rows`,
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

            {invalidTotal > 0 && file && (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="secondary"
                  className="min-h-11"
                  disabled={busy}
                  onClick={() => fixFileMutation.mutate(file)}
                >
                  {t({
                    zh: "下载待修正数据（全部错误行）",
                    en: "Download rows to fix (all errors)",
                  })}
                </Button>
                <span className="text-xs text-muted-foreground">
                  {t({
                    zh: "修正后连同辅助列直接重新上传即可",
                    en: "Fix and re-upload as-is; helper columns are ignored",
                  })}
                </span>
              </div>
            )}

            {preview.suspected.length > 0 && (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-amber-600 dark:text-amber-400">
                    {t({
                      zh: `疑似重复（默认跳过，勾选后导入）`,
                      en: `Possible duplicates (skipped unless checked)`,
                    })}
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      className="min-h-9"
                      onClick={() =>
                        setDecisions(
                          Object.fromEntries(
                            preview.suspected.map((item) => [
                              `${item.type}:${item.line}`,
                              true,
                            ]),
                          ),
                        )
                      }
                    >
                      {t({ zh: "全部导入", en: "Import all" })}
                    </Button>
                    <Button
                      variant="outline"
                      className="min-h-9"
                      onClick={() => setDecisions({})}
                    >
                      {t({ zh: "全部跳过", en: "Skip all" })}
                    </Button>
                  </div>
                </div>
                <ul className="max-h-64 space-y-2 overflow-y-auto">
                  {preview.suspected.map((item) => {
                    const key = `${item.type}:${item.line}`
                    const checked = decisions[key] === true
                    return (
                      <li
                        key={key}
                        className="space-y-2 rounded-lg border border-border bg-card p-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-xs text-muted-foreground">
                            {issueText(t, {
                              type: item.type,
                              line: item.line,
                              reason: item.reason,
                            })}
                          </span>
                          <div className="flex gap-2">
                            <Button
                              variant={checked ? "default" : "outline"}
                              className="min-h-11"
                              onClick={() =>
                                setDecisions((prev) => ({
                                  ...prev,
                                  [key]: true,
                                }))
                              }
                            >
                              {t({ zh: "导入", en: "Import" })}
                            </Button>
                            <Button
                              variant={!checked ? "secondary" : "outline"}
                              className="min-h-11"
                              onClick={() =>
                                setDecisions((prev) => ({
                                  ...prev,
                                  [key]: false,
                                }))
                              }
                            >
                              {t({ zh: "跳过", en: "Skip" })}
                            </Button>
                          </div>
                        </div>
                        <DiffTable
                          incoming={item.incoming}
                          existing={item.existing}
                        />
                      </li>
                    )
                  })}
                </ul>
                {preview.suspected_truncated && (
                  <p className="text-xs text-muted-foreground">
                    {t({
                      zh: `仅展示前 ${preview.suspected.length} 条（共 ${suspectedTotal} 条疑似）`,
                      en: `First ${preview.suspected.length} of ${suspectedTotal} shown`,
                    })}
                  </p>
                )}
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
                    {t({
                      zh: "仅展示前 200 条，下载待修正数据可看全量",
                      en: "First 200 shown; download rows-to-fix for the full list",
                    })}
                  </p>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Button
                className="min-h-11"
                disabled={busy || effectiveValid === 0}
                onClick={confirmImport}
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
                        zh: `跳过疑似 ${sheet.skipped_suspected}`,
                        en: `${sheet.skipped_suspected} possible duplicates skipped`,
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

            {createdItems.length > 0 && (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="secondary"
                    className="min-h-11"
                    onClick={() => {
                      setShowBatch((v) => !v)
                      setShowAudioFix(false)
                    }}
                  >
                    {t({
                      zh: `查看本批题目（${createdItems.length}）`,
                      en: `View this batch (${createdItems.length})`,
                    })}
                  </Button>
                  {audioFixItems.length > 0 && (
                    <Button
                      variant="secondary"
                      className="min-h-11"
                      onClick={() => {
                        setShowAudioFix((v) => !v)
                        setShowBatch(false)
                      }}
                    >
                      {t({
                        zh: `补齐音频（${audioFixItems.length}）`,
                        en: `Add audio (${audioFixItems.length})`,
                      })}
                    </Button>
                  )}
                  <Button
                    className="min-h-11"
                    onClick={() => sendToComposer(createdItems)}
                  >
                    {t({ zh: "带入组卷", en: "Send to composer" })}
                  </Button>
                </div>

                {showBatch && (
                  <ul className="max-h-48 space-y-1 overflow-y-auto rounded-lg border border-border bg-card p-2">
                    {createdItems.map((item) => (
                      <li
                        key={`${item.type}-${item.id}`}
                        className="flex flex-wrap items-center gap-2 text-xs"
                      >
                        <Badge variant="secondary">
                          {t(questionBankTypeLabel(item.type))}
                        </Badge>
                        <span>{item.label}</span>
                        {item.needs_audio && item.audio_missing && (
                          <span className="text-amber-600 dark:text-amber-400">
                            {t({ zh: "缺音频", en: "no audio" })}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}

                {showAudioFix && (
                  <div className="space-y-3 rounded-lg border border-border bg-card p-3 text-xs">
                    <p className="text-amber-600 dark:text-amber-400">
                      {t({
                        zh: "自动考试要求所有非朗读题配齐音频才能发布（不能依赖开考时合成）；普通练习可用文字与设备合成兜底。以下题目建议补齐：",
                        en: "Automated exams reject any non-reading item without audio at publish time (no on-start synthesis fallback); normal practice falls back to text and device TTS. Recommended fixes:",
                      })}
                    </p>
                    {(["repeat", "question", "instruction"] as const).map(
                      (kind) => {
                        const items = audioFixItems.filter(
                          (i) => i.type === kind,
                        )
                        if (items.length === 0) {
                          return null
                        }
                        return (
                          <div key={kind} className="space-y-1">
                            <p className="font-medium">
                              {t(questionBankTypeLabel(kind))}（{items.length}）
                            </p>
                            <ul className="max-h-32 space-y-1 overflow-y-auto">
                              {items.map((item) => (
                                <li key={item.id}>· {item.label}</li>
                              ))}
                            </ul>
                            {kind === "repeat" && (
                              <Button
                                variant="link"
                                className="min-h-9 px-0 text-xs"
                                onClick={() => {
                                  onOpenChange(false)
                                  void navigate({ to: "/create" })
                                }}
                              >
                                {t({
                                  zh: "去题目库处理：挂靠篇目的句子在「文章朗读 · 篇目」编辑里，独立句在「听句复述」区 →",
                                  en: "Open the Question Bank: attached sentences are edited under Read Aloud · Passages; standalone ones in Listen & Repeat →",
                                })}
                              </Button>
                            )}
                            {kind === "question" && (
                              <Button
                                variant="link"
                                className="min-h-9 px-0 text-xs"
                                onClick={() => {
                                  onOpenChange(false)
                                  void navigate({ to: "/admin/scenarios" })
                                }}
                              >
                                {t({
                                  zh: "去情景问答，在各主题的题目编辑里上传/生成音频 →",
                                  en: "Open Scenario Q&A to upload/generate audio in each topic →",
                                })}
                              </Button>
                            )}
                            {kind === "instruction" && (
                              <p className="text-muted-foreground">
                                {t({
                                  zh: "题目说明的考试音频在发布考试时的逐题设置里配置（普通练习无需）。",
                                  en: "Exam audio for instructions is configured in per-item settings when publishing an exam (not needed for normal practice).",
                                })}
                              </p>
                            )}
                          </div>
                        )
                      },
                    )}
                  </div>
                )}
              </div>
            )}

            {result.missing_audio_total > 0 && (
              <p className="text-xs text-muted-foreground">
                {t({
                  zh: `本批共 ${result.missing_audio_total} 题暂无音频（朗读/问答有文字与合成兜底，可用于普通练习）。`,
                  en: `${result.missing_audio_total} item(s) have no audio yet (reading/Q&A fall back to text and synthesis for practice).`,
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
