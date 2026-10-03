import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ClipboardPaste, Pencil, Trash2 } from "lucide-react"
import { useMemo, useState } from "react"
import { AdminService, type QuestionBankOut } from "@/client"
import { ContentNavigation } from "@/components/Admin/ContentNavigation"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { APP_NAME } from "@/config"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import {
  EXAM_KIND_LABELS,
  EXAM_LEVEL_LABELS,
  VOCAB_LEVEL_ORDER,
} from "@/lib/terms"

export const Route = createFileRoute("/_layout/admin/questions")({
  component: QuestionsAdmin,
  head: () => ({
    meta: [{ title: `题库 / Question Bank - ${APP_NAME}` }],
  }),
})

const ALL_TOPICS = "__all__"

interface BatchItem {
  text: string
  translation: string | null
  suggested_seconds: number
}

type ParsedLine =
  | { ok: true; lineno: number; item: BatchItem }
  | { ok: false; lineno: number; reason: string }

/** 解析一行「英文 | 中文提示 | 秒数」（中文与秒数可省略）。校验文案随语言切换。 */
function parseLine(
  line: string,
  lineno: number,
  t: ReturnType<typeof useI18n>["t"],
): ParsedLine {
  const parts = line.split("|").map((p) => p.trim())
  const [text, translation, seconds] = parts
  if (!text)
    return {
      ok: false,
      lineno,
      reason: t({ zh: "题目内容为空", en: "Question text is empty" }),
    }
  if (seconds !== undefined && seconds !== "" && !/^\d+$/.test(seconds)) {
    return {
      ok: false,
      lineno,
      reason: t({
        zh: `秒数「${seconds}」不是整数`,
        en: `Seconds "${seconds}" is not a whole number`,
      }),
    }
  }
  if (seconds) {
    const n = Number(seconds)
    if (n < 10 || n > 60) {
      return {
        ok: false,
        lineno,
        reason: t({
          zh: `秒数 ${n} 需在 10–60 之间`,
          en: `Seconds must be between 10 and 60 (got ${n})`,
        }),
      }
    }
  }
  return {
    ok: true,
    lineno,
    item: {
      text,
      translation: translation || null,
      suggested_seconds: seconds ? Number(seconds) : 20,
    },
  }
}

export function QuestionsAdmin({ embedded = false }: { embedded?: boolean }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const scenariosQuery = useQuery({
    queryKey: ["admin", "scenarios"],
    queryFn: () => AdminService.listScenarios(),
  })

  // ── 筛选 ──
  const [filterTopic, setFilterTopic] = useState(ALL_TOPICS)
  const [keyword, setKeyword] = useState("")
  const [search, setSearch] = useState("")

  const bankQuery = useQuery({
    queryKey: ["admin", "question-bank", filterTopic, search],
    queryFn: () =>
      AdminService.listQuestionBank({
        topic: filterTopic === ALL_TOPICS ? undefined : filterTopic,
        q: search || undefined,
      }),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "question-bank"] })
    void queryClient.invalidateQueries({ queryKey: ["admin", "scenarios"] })
  }

  // ── 批量录入 ──
  const [batchTopic, setBatchTopic] = useState("")
  const [batchText, setBatchText] = useState("")

  const parsed = useMemo(() => {
    const results: ParsedLine[] = batchText
      .split("\n")
      .map((raw, i) => ({ raw, lineno: i + 1 }))
      .filter(({ raw }) => raw.trim().length > 0)
      .map(({ raw, lineno }) => parseLine(raw, lineno, t))
    return {
      items: results.flatMap((r) => (r.ok ? [r.item] : [])),
      problems: results.flatMap((r) => (r.ok ? [] : [r])),
    }
  }, [batchText, t])

  const scenarioId = (scenariosQuery.data ?? []).find(
    (s) => s.topic === batchTopic,
  )?.id

  const batchMutation = useMutation({
    mutationFn: () =>
      AdminService.createQuestionsBatch({
        scenarioId: scenarioId ?? "",
        requestBody: { items: parsed.items },
      }),
    onSuccess: (result) => {
      if (result.failed.length === 0) {
        showSuccessToast(
          t({
            zh: `已录入 ${result.created} 道题`,
            en: `Added ${result.created} questions`,
          }),
        )
      } else {
        showErrorToast(
          t({
            zh: `录入 ${result.created} 道，${result.failed.length} 道被拒（第 ${result.failed
              .map((f) => f.index + 1)
              .join("、")} 行：${result.failed[0]?.reason}）`,
            en: `Added ${result.created}, rejected ${result.failed.length} (line ${result.failed
              .map((f) => f.index + 1)
              .join(", ")}: ${result.failed[0]?.reason})`,
          }),
        )
      }
      if (result.created > 0) {
        setBatchText("")
        invalidate()
      }
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `批量录入失败：${error.message}`,
          en: `Bulk add failed: ${error.message}`,
        }),
      ),
  })

  // ── 编辑 / 删除 ──
  const [editing, setEditing] = useState<QuestionBankOut | null>(null)
  const [editForm, setEditForm] = useState({
    text: "",
    translation: "",
    suggested_seconds: 20,
    exam_kind: "",
    exam_level: "",
    cue_card_bullets: "",
    prep_seconds: "",
  })
  const [toDelete, setToDelete] = useState<QuestionBankOut | null>(null)

  const openEdit = (row: QuestionBankOut) => {
    setEditing(row)
    setEditForm({
      text: row.text,
      translation: row.translation ?? "",
      suggested_seconds: row.suggested_seconds,
      exam_kind: row.exam_kind ?? "",
      exam_level: row.exam_level ?? "",
      cue_card_bullets: (row.cue_card_bullets ?? []).join("\n"),
      prep_seconds: row.prep_seconds ? String(row.prep_seconds) : "",
    })
  }

  const updateMutation = useMutation({
    mutationFn: () =>
      AdminService.updateQuestion({
        questionId: editing!.id,
        requestBody: {
          text: editForm.text.trim(),
          translation: editForm.translation.trim() || null,
          suggested_seconds: editForm.suggested_seconds,
          exam_kind: editForm.exam_kind || null,
          exam_level: editForm.exam_level || null,
          cue_card_bullets:
            editForm.exam_kind === "ielts_p2" &&
            editForm.cue_card_bullets.trim()
              ? editForm.cue_card_bullets
                  .split("\n")
                  .map((line) => line.trim())
                  .filter(Boolean)
              : null,
          prep_seconds:
            editForm.exam_kind === "ielts_p2" && editForm.prep_seconds
              ? Number(editForm.prep_seconds)
              : null,
        },
      }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "题目已更新", en: "Question updated" }))
      setEditing(null)
      invalidate()
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `更新失败：${error.message}`,
          en: `Update failed: ${error.message}`,
        }),
      ),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => AdminService.deleteQuestion({ questionId: id }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "题目已删除", en: "Question deleted" }))
      setToDelete(null)
      invalidate()
    },
    onError: (error) =>
      showErrorToast(
        t({
          zh: `删除失败：${error.message}`,
          en: `Delete failed: ${error.message}`,
        }),
      ),
  })

  const topics = (scenariosQuery.data ?? []).map((s) => s.topic)
  const rows = bankQuery.data ?? []
  const editValid =
    editForm.text.trim().length > 0 &&
    editForm.suggested_seconds >= 10 &&
    editForm.suggested_seconds <= 60

  return (
    <div className="flex flex-col gap-6">
      {!embedded && <ContentNavigation />}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t({ zh: "情景问答 · 题目管理", en: "Scenario Q&A · Questions" })}
        </h1>
        <p className="text-muted-foreground">
          {t({
            zh: "情景问答的集中管理：跨主题搜索、批量粘贴录入、逐条修改。学生每轮练习从对应主题的题目里按序抽取。",
            en: "Central management for Scenario Q&A: search across topics, paste in bulk, and edit one by one. Each practice round draws questions in order from the matching topic.",
          })}
        </p>
      </div>

      <details className="rounded-xl border bg-card p-4">
        <summary className="cursor-pointer font-medium text-primary">
          {t({ zh: "批量录入问答题", en: "Bulk Add Questions" })}
        </summary>
        <div className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ClipboardPaste className="size-4" />
                {t({ zh: "批量录入", en: "Bulk Add" })}
              </CardTitle>
              <CardDescription>
                {t({
                  zh: "每行一道题，格式「英文题目 | 中文提示 | 建议秒数」，中文和秒数可省略（默认 20 秒）。",
                  en: 'One question per line, formatted as "English question | Chinese hint | suggested seconds"; the hint and seconds are optional (default 20).',
                })}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <Label>{t({ zh: "主题", en: "Topic" })}</Label>
                <Select
                  value={batchTopic}
                  onValueChange={setBatchTopic}
                  disabled={topics.length === 0}
                >
                  <SelectTrigger>
                    <SelectValue
                      placeholder={
                        topics.length === 0
                          ? t({
                              zh: "还没有主题，先去「问答主题与出题」建一个",
                              en: "No topics yet — create one in Topics & Questions first",
                            })
                          : t({ zh: "选择题库主题", en: "Select a bank topic" })
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {topics.map((topic) => (
                      <SelectItem key={topic} value={topic}>
                        {topic}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Textarea
                rows={6}
                value={batchText}
                onChange={(e) => setBatchText(e.target.value)}
                placeholder={
                  "How do you get to school? | 你怎样去学校？ | 20\nWhat is your favourite subject? | 你最喜欢哪门学科？"
                }
                aria-label={t({ zh: "批量录入题目", en: "Bulk add questions" })}
              />
              {batchText.trim() && (
                <div className="text-sm text-muted-foreground">
                  {t({ zh: "将录入", en: "Adding" })}{" "}
                  <span className="font-medium text-foreground">
                    {parsed.items.length}
                  </span>{" "}
                  {t({ zh: "道题", en: "questions" })}
                  {parsed.problems.length > 0 && (
                    <span className="text-destructive">
                      {" "}
                      ·{" "}
                      {t({
                        zh: `${parsed.problems.length} 行有问题：`,
                        en: `${parsed.problems.length} lines with problems: `,
                      })}
                      {parsed.problems
                        .map((p) =>
                          t({
                            zh: `第${p.lineno}行（${p.reason}）`,
                            en: `line ${p.lineno} (${p.reason})`,
                          }),
                        )
                        .join(t({ zh: "、", en: ", " }))}
                    </span>
                  )}
                </div>
              )}
              <div>
                <LoadingButton
                  disabled={!scenarioId || parsed.items.length === 0}
                  loading={batchMutation.isPending}
                  onClick={() => batchMutation.mutate()}
                >
                  {t({
                    zh: `录入${parsed.items.length > 0 ? ` ${parsed.items.length} 道题` : ""}`,
                    en:
                      parsed.items.length > 0
                        ? `Add ${parsed.items.length} Questions`
                        : "Add",
                  })}
                </LoadingButton>
              </div>
            </CardContent>
          </Card>
        </div>
      </details>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t({ zh: "全部题目", en: "All Questions" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: `共 ${rows.length} 条，按主题、序号排列。`,
              en: `${rows.length} in total, ordered by topic and index.`,
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Select value={filterTopic} onValueChange={setFilterTopic}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_TOPICS}>
                  {t({ zh: "全部主题", en: "All Topics" })}
                </SelectItem>
                {topics.map((topic) => (
                  <SelectItem key={topic} value={topic}>
                    {topic}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                setSearch(keyword.trim())
              }}
            >
              <Input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder={t({
                  zh: "搜题目或中文提示…",
                  en: "Search questions or hints…",
                })}
                aria-label={t({ zh: "搜索题目", en: "Search questions" })}
              />
              <Button type="submit" variant="outline">
                {t({ zh: "搜索", en: "Search" })}
              </Button>
            </form>
          </div>

          {bankQuery.isPending ? (
            <div className="flex flex-col gap-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : bankQuery.isError ? (
            <div className="flex flex-col items-center gap-3 py-8 text-muted-foreground">
              <p>
                {t({ zh: "题库加载失败。", en: "Failed to load questions." })}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void bankQuery.refetch()}
              >
                {t({ zh: "重试", en: "Retry" })}
              </Button>
            </div>
          ) : rows.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              {t({
                zh: "没有符合条件的题目，换个筛选条件或在上面批量录入。",
                en: "No questions match — adjust the filters or bulk add above.",
              })}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t({ zh: "主题", en: "Topic" })}</TableHead>
                  <TableHead>{t({ zh: "题目", en: "Question" })}</TableHead>
                  <TableHead>
                    {t({ zh: "中文提示", en: "Chinese Hint" })}
                  </TableHead>
                  <TableHead className="w-16">
                    {t({ zh: "秒数", en: "Secs" })}
                  </TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>{row.topic}</TableCell>
                    <TableCell className="max-w-96 font-medium">
                      {row.text}
                    </TableCell>
                    <TableCell className="max-w-56 text-muted-foreground">
                      {row.translation ?? "—"}
                    </TableCell>
                    <TableCell>{row.suggested_seconds}s</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={t({
                            zh: "编辑题目",
                            en: "Edit question",
                          })}
                          onClick={() => openEdit(row)}
                        >
                          <Pencil />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={t({
                            zh: "删除题目",
                            en: "Delete question",
                          })}
                          onClick={() => setToDelete(row)}
                        >
                          <Trash2 className="text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "编辑题目", en: "Edit Question" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "修改会即时生效；学生下一轮抽题时使用新内容。",
                en: "Changes take effect immediately; students see the new content next round.",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="q-text">
                {t({ zh: "英文题目", en: "Question" })}
              </Label>
              <Textarea
                id="q-text"
                rows={3}
                value={editForm.text}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, text: e.target.value }))
                }
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="q-translation">
                {t({ zh: "中文提示（可选）", en: "Chinese Hint (optional)" })}
              </Label>
              <Input
                id="q-translation"
                value={editForm.translation}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, translation: e.target.value }))
                }
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="q-seconds">
                {editForm.exam_kind
                  ? t({
                      zh: "作答秒数（10–300，考试题支持长回答）",
                      en: "Answer Seconds (10–300, exam tasks allow long answers)",
                    })
                  : t({
                      zh: "建议秒数（10–60）",
                      en: "Suggested Seconds (10–60)",
                    })}
              </Label>
              <Input
                id="q-seconds"
                type="number"
                min={10}
                max={editForm.exam_kind ? 300 : 60}
                value={editForm.suggested_seconds}
                onChange={(e) =>
                  setEditForm((f) => ({
                    ...f,
                    suggested_seconds: Number(e.target.value),
                  }))
                }
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor="q-exam-kind">
                  {t({ zh: "考试题型（可选）", en: "Exam task (optional)" })}
                </Label>
                <select
                  id="q-exam-kind"
                  value={editForm.exam_kind}
                  onChange={(e) =>
                    setEditForm((f) => ({
                      ...f,
                      exam_kind: e.target.value,
                      cue_card_bullets:
                        e.target.value === "ielts_p2" ? f.cue_card_bullets : "",
                      prep_seconds:
                        e.target.value === "ielts_p2" ? f.prep_seconds : "",
                    }))
                  }
                  className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
                >
                  <option value="">
                    {t({ zh: "普通情景问法", en: "Regular question" })}
                  </option>
                  {Object.entries(EXAM_KIND_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {t(label)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="q-exam-level">
                  {t({ zh: "级别（可选）", en: "Level (optional)" })}
                </Label>
                <select
                  id="q-exam-level"
                  value={editForm.exam_level}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, exam_level: e.target.value }))
                  }
                  className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
                >
                  <option value="">
                    {t({ zh: "不标注", en: "Unlabeled" })}
                  </option>
                  {VOCAB_LEVEL_ORDER.map((level) => (
                    <option key={level} value={level}>
                      {t(EXAM_LEVEL_LABELS[level])}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            {editForm.exam_kind === "ielts_p2" && (
              <div className="flex flex-col gap-2">
                <Label htmlFor="q-cue-card">
                  {t({
                    zh: "话题卡要点（每行一条）",
                    en: "Cue card points (one per line)",
                  })}
                </Label>
                <Textarea
                  id="q-cue-card"
                  rows={3}
                  value={editForm.cue_card_bullets}
                  onChange={(e) =>
                    setEditForm((f) => ({
                      ...f,
                      cue_card_bullets: e.target.value,
                    }))
                  }
                  placeholder={t({
                    zh: "如：它在哪里\n你和谁一起过",
                    en: "e.g. Where it is\nWho you spend it with",
                  })}
                />
                <Label htmlFor="q-prep" className="mt-1">
                  {t({
                    zh: "准备时间秒数（10–180）",
                    en: "Prep seconds (10–180)",
                  })}
                </Label>
                <Input
                  id="q-prep"
                  type="number"
                  min={10}
                  max={180}
                  value={editForm.prep_seconds}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, prep_seconds: e.target.value }))
                  }
                />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <LoadingButton
              disabled={!editValid}
              loading={updateMutation.isPending}
              onClick={() => updateMutation.mutate()}
            >
              {t({ zh: "保存", en: "Save" })}
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={toDelete !== null}
        title={t({ zh: "删除这道题？", en: "Delete this question?" })}
        description={t({
          zh: `「${toDelete?.text ?? ""}」删除后学生抽题不再出现，历史作答保留。此操作不可撤销。`,
          en: `"${toDelete?.text ?? ""}" will no longer be drawn for students; past answers are kept. This cannot be undone.`,
        })}
        confirmText={t({ zh: "删除题目", en: "Delete Question" })}
        onOpenChange={(next) => {
          if (!next) setToDelete(null)
        }}
        onConfirm={async () => {
          if (toDelete) await deleteMutation.mutateAsync(toDelete.id)
        }}
      />
    </div>
  )
}
