import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  BookA,
  CheckCircle2,
  Download,
  Loader2,
  ShieldCheck,
  Upload,
} from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { ApiError, VocabLevelsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { APP_NAME } from "@/config"
import { downloadCsv } from "@/lib/csv"
import { useI18n } from "@/lib/i18n"
import {
  VOCAB_LEVEL_LABELS,
  VOCAB_LEVEL_ORDER,
  type VocabLevel,
} from "@/lib/terms"
import { localizeImportIssue } from "@/lib/vocabImport"

export const Route = createFileRoute("/_layout/admin/vocablevels")({
  component: VocabLevelsAdmin,
  head: () => ({
    meta: [{ title: `五级词库 / Leveled Word Source - ${APP_NAME}` }],
  }),
})

type LevelImportIssue = {
  kind: string
  line: number
  headword: string
  reason: string
  existing_level?: string | null
}

type LevelPreview = {
  level: string
  source_label: string
  invalid: LevelImportIssue[]
  duplicates_in_file: LevelImportIssue[]
  cross_level_conflicts: LevelImportIssue[]
  new_count: number
  merge_count: number
  counts_after: Array<{
    level: string
    entry_count?: number
    phrase_count?: number
    needs_review_count?: number
  }>
}

function VocabLevelsAdmin() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)

  const statsQuery = useQuery({
    queryKey: ["admin", "vocab-levels", "stats"],
    queryFn: () => VocabLevelsService.vocabLevelStats(),
  })

  // 导入表单状态。预览与参数绑定（P2-5）：级别/来源/文件任一变化即作废预览，
  // 确认导入只能使用预览时固定的 file+level+source_label，杜绝错级导入
  const [importLevel, setImportLevel] = useState<VocabLevel>("KET")
  const [sourceLabel, setSourceLabel] = useState("")
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<LevelPreview | null>(null)
  const [previewParams, setPreviewParams] = useState<{
    file: File
    level: VocabLevel
    sourceLabel: string
  } | null>(null)
  const discardPreview = () => {
    setPreview(null)
    setPreviewParams(null)
  }

  const previewMutation = useMutation({
    mutationFn: async () => {
      if (!pendingFile) throw new Error("no file")
      const params = {
        file: pendingFile,
        level: importLevel,
        sourceLabel:
          sourceLabel.trim() || pendingFile.name.replace(/\.[^.]+$/, ""),
      }
      const data = await VocabLevelsService.vocabLevelImportPreview({
        formData: {
          file: pendingFile as unknown as string,
          level: params.level,
          source_label: params.sourceLabel,
        },
      })
      setPreviewParams(params)
      return data
    },
    onSuccess: (data) => setPreview(data as LevelPreview),
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(
          error.status === 422
            ? t({
                zh: "文件格式有误：需要 UTF-8 的 CSV/TXT（表头 headword,part_of_speech,meaning_zh 或每行一词）。",
                en: "Bad file: UTF-8 CSV/TXT required (header headword,part_of_speech,meaning_zh, or one word per line).",
              })
            : t({
                zh: "预览失败，请重试。",
                en: "Preview failed — please retry.",
              }),
        )
      }
    },
  })

  const confirmMutation = useMutation({
    mutationFn: async () => {
      // 用预览时固定的参数（评审 P2-5）
      if (!previewParams) throw new Error("no preview")
      return VocabLevelsService.vocabLevelImportConfirm({
        formData: {
          file: previewParams.file as unknown as string,
          level: previewParams.level,
          source_label: previewParams.sourceLabel,
        },
      })
    },
    onSuccess: (data) => {
      toast.success(
        t({
          zh: `已导入：新增 ${data.imported_new} 条、合并 ${data.merged_existing} 条、跳过无效 ${data.skipped_invalid} 行。`,
          en: `Imported: ${data.imported_new} new, ${data.merged_existing} merged, ${data.skipped_invalid} invalid rows skipped.`,
        }),
      )
      discardPreview()
      setPendingFile(null)
      queryClient.invalidateQueries({ queryKey: ["admin", "vocab-levels"] })
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(
          error.status === 422
            ? t({
                zh: "导入内容有误，已整体回滚。",
                en: "Import rejected and rolled back.",
              })
            : t({
                zh: "导入失败，请重试。",
                en: "Import failed — please retry.",
              }),
        )
      }
    },
  })

  // 待人工核对词条（分页 + 补录释义）
  const PAGE_SIZE = 50
  const [reviewFilter, setReviewFilter] = useState<"all" | "needs_review">(
    "needs_review",
  )
  const [page, setPage] = useState(0)
  const [editing, setEditing] = useState<{
    id: string
    headword: string
    meaning: string
    pos: string
  } | null>(null)

  const entriesQuery = useQuery({
    queryKey: ["admin", "vocab-levels", "entries", reviewFilter, page],
    queryFn: () =>
      VocabLevelsService.listVocabLevelEntries({
        needsReview: reviewFilter === "needs_review" ? true : undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
  })

  const saveReview = useMutation({
    mutationFn: (payload: {
      id: string
      meaning: string
      pos: string
      markReviewed: boolean
    }) =>
      VocabLevelsService.updateVocabLevelEntry({
        entryId: payload.id,
        requestBody: {
          meaning_zh: payload.meaning.trim() || null,
          part_of_speech: payload.pos.trim() || null,
          needs_review: payload.markReviewed ? false : undefined,
        },
      }),
    onSuccess: () => {
      toast.success(t({ zh: "已保存。", en: "Saved." }))
      setEditing(null)
      queryClient.invalidateQueries({ queryKey: ["admin", "vocab-levels"] })
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(
          error.status === 422
            ? t({
                zh: "保存失败：释义为空时不能标记已核对。",
                en: "Save failed: an entry without a meaning can't be marked reviewed.",
              })
            : t({
                zh: "保存失败，请重试。",
                en: "Save failed — please retry.",
              }),
        )
      }
    },
  })

  const exportButtonDisabled = entriesQuery.isPending

  const exportNeedsReview = async () => {
    // 导出全部（按页拉取，不受单页 50 条限制）
    const all: NonNullable<typeof entriesQuery.data> = []
    for (let offset = 0; ; offset += 500) {
      const batch = await VocabLevelsService.listVocabLevelEntries({
        needsReview: reviewFilter === "needs_review" ? true : undefined,
        limit: 500,
        offset,
      })
      all.push(...batch)
      if (batch.length < 500) break
    }
    const rows = all
    downloadCsv(
      [
        [
          t({ zh: "级别", en: "Level" }),
          t({ zh: "单词", en: "Headword" }),
          t({ zh: "词性", en: "POS" }),
          t({ zh: "释义", en: "Meaning" }),
          t({ zh: "来源", en: "Sources" }),
        ],
        ...rows.map((row) => [
          row.level,
          row.headword,
          row.part_of_speech ?? "",
          row.meaning_zh ?? "",
          (row.sources ?? []).join("; "),
        ]),
      ],
      t({
        zh: `五级词库-待核对-${new Date().toISOString().slice(0, 10)}.csv`,
        en: `leveled-vocab-needs-review-${new Date().toISOString().slice(0, 10)}.csv`,
      }),
    )
  }

  const stats = statsQuery.data
  const entries = entriesQuery.data ?? []

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t({ zh: "五级词库", en: "Leveled Word Source" })}
        </h1>
        <p className="text-muted-foreground">
          {t({
            zh: "口语模块与背单词模块共用的统一分级数据源。级别固定顺序 KET → PET → 学术 → 四级 → 雅思&托福；同词出现在多级时实际难度取最早（最易）一级。学校资料未确认线上使用授权前，请勿在此导入生产环境。",
            en: "The shared leveled source for both the speaking and vocabulary modules. Fixed order: KET → PET → Academic → CET-4 → IELTS & TOEFL; a word appearing at several levels takes the earliest (easiest) one. Do not import school materials into production before usage rights are confirmed.",
          })}
        </p>
      </div>

      {/* 各级数量 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {VOCAB_LEVEL_ORDER.map((level) => {
          const count = (stats?.levels ?? []).find(
            (item) => item.level === level,
          )
          return (
            <Card key={level}>
              <CardContent className="py-4">
                <p className="text-xs text-muted-foreground">
                  {t(VOCAB_LEVEL_LABELS[level])}
                </p>
                <p className="mt-1 text-2xl font-bold tabular-nums">
                  {statsQuery.isPending ? "…" : (count?.entry_count ?? 0)}
                </p>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {t({ zh: "词组", en: "phrases" })} {count?.phrase_count ?? 0}
                  {(count?.needs_review_count ?? 0) > 0 && (
                    <span className="ml-2 text-amber-600">
                      {t({ zh: "待核对", en: "review" })}{" "}
                      {count?.needs_review_count}
                    </span>
                  )}
                </p>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* 分级导入 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({
              zh: "分级导入（预览 → 确认）",
              en: "Import by level (preview → confirm)",
            })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "CSV/TXT：表头 headword,part_of_speech,meaning_zh（后两列可选），或每行一词。预览会给出无效行、批内重复、跨级冲突与导入后各级数量；确认导入为单事务，失败整体回滚。",
              en: "CSV/TXT with header headword,part_of_speech,meaning_zh (last two optional), or one word per line. The preview lists invalid rows, in-file duplicates, cross-level conflicts and post-import counts; confirming runs in one transaction and rolls back on any failure.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <label htmlFor="level-select" className="text-sm font-medium">
                {t({ zh: "导入级别", en: "Level" })}
              </label>
              <select
                id="level-select"
                value={importLevel}
                onChange={(event) =>
                  setImportLevel(event.target.value as VocabLevel)
                }
                className="h-11 w-full rounded-xl border border-input bg-card px-3 text-base text-foreground transition-colors hover:border-primary/35"
              >
                {VOCAB_LEVEL_ORDER.map((level) => (
                  <option key={level} value={level}>
                    {t(VOCAB_LEVEL_LABELS[level])}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="source-label" className="text-sm font-medium">
                {t({ zh: "来源标签", en: "Source label" })}
              </label>
              <Input
                id="source-label"
                value={sourceLabel}
                onChange={(event) => {
                  setSourceLabel(event.target.value)
                  discardPreview()
                }}
                placeholder={t({
                  zh: "如：KET整理版（默认用文件名）",
                  en: "e.g. KET wordlist (defaults to filename)",
                })}
                className="h-11 text-base"
              />
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">
                {t({ zh: "数据文件", en: "Data file" })}
              </span>
              <div className="flex h-11 items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fileRef.current?.click()}
                  disabled={previewMutation.isPending}
                >
                  {previewMutation.isPending ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <Upload />
                  )}
                  {pendingFile
                    ? pendingFile.name
                    : t({ zh: "选择 CSV/TXT", en: "Choose CSV/TXT" })}
                </Button>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".csv,.txt,text/csv,text/plain"
                  className="hidden"
                  onChange={async (event) => {
                    const file = event.target.files?.[0] ?? null
                    setPendingFile(file)
                    discardPreview()
                    if (file && file.size > 5 * 1024 * 1024) {
                      toast.error(
                        t({
                          zh: "文件超过 5MB 上限",
                          en: "File exceeds the 5MB limit",
                        }),
                      )
                      setPendingFile(null)
                    }
                    event.target.value = ""
                  }}
                />
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={!pendingFile || previewMutation.isPending}
              onClick={() => previewMutation.mutate()}
            >
              {previewMutation.isPending ? (
                <Loader2 className="animate-spin" />
              ) : null}
              {t({ zh: "生成预览", en: "Preview" })}
            </Button>
            {pendingFile && previewParams === null && preview === null && (
              <span className="self-center text-xs text-muted-foreground">
                {t({
                  zh: "请先生成预览，确认无误后再导入。",
                  en: "Generate a preview first; import only after review.",
                })}
              </span>
            )}
          </div>

          {preview && (
            <div className="space-y-3 rounded-xl border border-dashed border-primary/40 bg-secondary/40 p-4">
              <p className="text-sm">
                {t({
                  zh: `预览：将新增 ${preview.new_count} 条、合并 ${preview.merge_count} 条（级别：${t(VOCAB_LEVEL_LABELS[preview.level as VocabLevel] ?? { zh: preview.level, en: preview.level })}，来源：${preview.source_label}）。`,
                  en: `Preview: ${preview.new_count} new, ${preview.merge_count} merged (level ${preview.level}, source ${preview.source_label}).`,
                })}
              </p>
              <div className="flex flex-wrap gap-2 text-xs">
                {preview.invalid.length > 0 && (
                  <Badge variant="destructive">
                    {t({
                      zh: `无效 ${preview.invalid.length} 行`,
                      en: `${preview.invalid.length} invalid`,
                    })}
                  </Badge>
                )}
                {preview.duplicates_in_file.length > 0 && (
                  <Badge variant="secondary">
                    {t({
                      zh: `批内重复 ${preview.duplicates_in_file.length} 行`,
                      en: `${preview.duplicates_in_file.length} in-file duplicates`,
                    })}
                  </Badge>
                )}
                {preview.cross_level_conflicts.length > 0 && (
                  <Badge variant="outline">
                    {t({
                      zh: `跨级冲突 ${preview.cross_level_conflicts.length} 词`,
                      en: `${preview.cross_level_conflicts.length} cross-level conflicts`,
                    })}
                  </Badge>
                )}
              </div>
              {(preview.invalid.length > 0 ||
                preview.duplicates_in_file.length > 0 ||
                preview.cross_level_conflicts.length > 0) && (
                <ul className="max-h-40 space-y-0.5 overflow-y-auto text-xs text-muted-foreground">
                  {[
                    ...preview.invalid,
                    ...preview.duplicates_in_file,
                    ...preview.cross_level_conflicts,
                  ]
                    .slice(0, 12)
                    .map((issue) => (
                      <li key={`${issue.kind}-${issue.line}-${issue.headword}`}>
                        {t({ zh: "第", en: "Line" })} {issue.line}{" "}
                        {t({ zh: "行", en: "" })}：{issue.headword} —{" "}
                        {t(localizeImportIssue(issue.reason))}
                        {issue.existing_level &&
                          ` (${t({ zh: "已存在于", en: "exists at" })} ${issue.existing_level})`}
                      </li>
                    ))}
                </ul>
              )}
              <div className="flex flex-wrap gap-2 border-t pt-3">
                <Button
                  size="sm"
                  disabled={
                    confirmMutation.isPending ||
                    previewParams === null ||
                    preview.new_count + preview.merge_count === 0
                  }
                  onClick={() => confirmMutation.mutate()}
                >
                  {confirmMutation.isPending ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <CheckCircle2 />
                  )}
                  {t({ zh: "确认导入", en: "Confirm import" })}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPreview(null)}
                >
                  {t({ zh: "取消", en: "Cancel" })}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 待人工核对 */}
      <Card>
        <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldCheck className="size-4 text-primary" />
              {t({ zh: "词条核对", en: "Entry review" })}
            </CardTitle>
            <CardDescription>
              {t({
                zh: "扫描件 OCR 行必须人工核对后才能用于两模块的分级统计。",
                en: "OCR rows from scanned files need manual review before they count toward either module's leveling.",
              })}
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <select
              value={reviewFilter}
              onChange={(event) =>
                setReviewFilter(event.target.value as "all" | "needs_review")
              }
              aria-label={t({ zh: "核对筛选", en: "Review filter" })}
              className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
            >
              <option value="needs_review">
                {t({ zh: "待人工核对", en: "Needs review" })}
              </option>
              <option value="all">
                {t({ zh: "全部词条", en: "All entries" })}
              </option>
            </select>
            <Button
              variant="outline"
              size="sm"
              disabled={exportButtonDisabled}
              onClick={() => void exportNeedsReview()}
            >
              <Download />
              {t({ zh: "导出", en: "Export" })}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="pb-0">
          {entriesQuery.isPending ? (
            <div role="status" className="pb-6 text-sm text-muted-foreground">
              {t({ zh: "正在加载词条…", en: "Loading entries…" })}
            </div>
          ) : entries.length === 0 ? (
            <p className="pb-6 text-sm text-muted-foreground">
              {t({
                zh: "没有符合条件的词条。",
                en: "No entries match the filter.",
              })}
            </p>
          ) : (
            <>
              <p className="pb-3 text-xs text-muted-foreground sm:hidden">
                {t({
                  zh: "横向滑动表格，可以查看完整词条。",
                  en: "Swipe the table sideways to see all fields.",
                })}
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t({ zh: "级别", en: "Level" })}</TableHead>
                    <TableHead>{t({ zh: "单词", en: "Headword" })}</TableHead>
                    <TableHead>{t({ zh: "词性", en: "POS" })}</TableHead>
                    <TableHead>{t({ zh: "释义", en: "Meaning" })}</TableHead>
                    <TableHead>{t({ zh: "来源", en: "Sources" })}</TableHead>
                    <TableHead>{t({ zh: "操作", en: "Actions" })}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {entries.map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell>
                        <Badge variant="outline">
                          {t(
                            VOCAB_LEVEL_LABELS[entry.level as VocabLevel] ?? {
                              zh: entry.level,
                              en: entry.level,
                            },
                          )}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-semibold">
                        {entry.headword}
                        {entry.is_phrase && (
                          <Badge variant="secondary" className="ml-1.5">
                            {t({ zh: "词组", en: "phrase" })}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {entry.part_of_speech ?? "–"}
                      </TableCell>
                      <TableCell>
                        {entry.meaning_zh ?? (
                          <span className="italic text-muted-foreground">
                            {t({ zh: "待补录", en: "to be filled" })}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="max-w-48 truncate text-xs text-muted-foreground">
                        {(entry.sources ?? []).join("；")}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1.5">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              setEditing({
                                id: entry.id,
                                headword: entry.headword,
                                meaning: entry.meaning_zh ?? "",
                                pos: entry.part_of_speech ?? "",
                              })
                            }
                          >
                            {entry.meaning_zh
                              ? t({ zh: "编辑释义", en: "Edit meaning" })
                              : t({ zh: "补录释义", en: "Add meaning" })}
                          </Button>
                          {entry.needs_review && (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={
                                saveReview.isPending ||
                                !entry.meaning_zh?.trim()
                              }
                              title={
                                entry.meaning_zh?.trim()
                                  ? undefined
                                  : t({
                                      zh: "补录释义后才能标记已核对",
                                      en: "Add a meaning first",
                                    })
                              }
                              onClick={() =>
                                saveReview.mutate({
                                  id: entry.id,
                                  meaning: entry.meaning_zh ?? "",
                                  pos: entry.part_of_speech ?? "",
                                  markReviewed: true,
                                })
                              }
                            >
                              <BookA />
                              {t({ zh: "标记已核对", en: "Mark reviewed" })}
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="flex items-center justify-between gap-3 py-4">
                <span className="text-xs text-muted-foreground">
                  {t({
                    zh: `第 ${page + 1} 页（每页 ${PAGE_SIZE} 条）`,
                    en: `Page ${page + 1} (${PAGE_SIZE} per page)`,
                  })}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 0}
                    onClick={() => setPage(page - 1)}
                  >
                    {t({ zh: "上一页", en: "Previous" })}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={(entriesQuery.data ?? []).length < PAGE_SIZE}
                    onClick={() => setPage(page + 1)}
                  >
                    {t({ zh: "下一页", en: "Next" })}
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* 补录/编辑释义对话框（服务端禁止空释义直接标记已核对） */}
      {editing && (
        <Card className="border-primary/30">
          <CardHeader>
            <CardTitle className="text-base">
              {t({ zh: "核对词条：", en: "Review entry: " })}
              <span className="font-mono">{editing.headword}</span>
            </CardTitle>
            <CardDescription>
              {t({
                zh: "补录中文释义与词性后，可标记为已核对（该词才开始参与两模块的分级统计）。",
                en: "Fill in the Chinese meaning and POS, then mark reviewed (the word then counts toward both modules' leveling).",
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="edit-meaning" className="text-sm font-medium">
                  {t({ zh: "中文释义", en: "Chinese meaning" })}
                </label>
                <Input
                  id="edit-meaning"
                  value={editing.meaning}
                  onChange={(event) =>
                    setEditing({ ...editing, meaning: event.target.value })
                  }
                  className="h-11 text-base"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="edit-pos" className="text-sm font-medium">
                  {t({ zh: "词性（可选）", en: "POS (optional)" })}
                </label>
                <Input
                  id="edit-pos"
                  value={editing.pos}
                  onChange={(event) =>
                    setEditing({ ...editing, pos: event.target.value })
                  }
                  className="h-11 text-base"
                />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={saveReview.isPending || editing.meaning.trim() === ""}
                onClick={() =>
                  saveReview.mutate({
                    id: editing.id,
                    meaning: editing.meaning,
                    pos: editing.pos,
                    markReviewed: true,
                  })
                }
              >
                {saveReview.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <CheckCircle2 />
                )}
                {t({ zh: "保存并标记已核对", en: "Save & mark reviewed" })}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={saveReview.isPending || editing.meaning.trim() === ""}
                onClick={() =>
                  saveReview.mutate({
                    id: editing.id,
                    meaning: editing.meaning,
                    pos: editing.pos,
                    markReviewed: false,
                  })
                }
              >
                {t({ zh: "仅保存", en: "Save only" })}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditing(null)}
              >
                {t({ zh: "取消", en: "Cancel" })}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <p className="pb-6 text-center text-xs text-muted-foreground">
        {t({
          zh: "导入只新增分级数据：已发布任务快照与历史 A2/B1/B2 词汇分析结果不会被重新解释。",
          en: "Imports only add leveling data: published task snapshots and historical A2/B1/B2 analyses are never re-interpreted.",
        })}
      </p>
    </div>
  )
}
