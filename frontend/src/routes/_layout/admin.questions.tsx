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

export const Route = createFileRoute("/_layout/admin/questions")({
  component: QuestionsAdmin,
  head: () => ({ meta: [{ title: `题库 - ${APP_NAME}` }] }),
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

/** 解析一行「英文 | 中文提示 | 秒数」（中文与秒数可省略）。 */
function parseLine(line: string, lineno: number): ParsedLine {
  const parts = line.split("|").map((p) => p.trim())
  const [text, translation, seconds] = parts
  if (!text) return { ok: false, lineno, reason: "题目内容为空" }
  if (seconds !== undefined && seconds !== "" && !/^\d+$/.test(seconds)) {
    return { ok: false, lineno, reason: `秒数「${seconds}」不是整数` }
  }
  if (seconds) {
    const n = Number(seconds)
    if (n < 10 || n > 60) {
      return { ok: false, lineno, reason: `秒数 ${n} 需在 10–60 之间` }
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
      .map(({ raw, lineno }) => parseLine(raw, lineno))
    return {
      items: results.flatMap((r) => (r.ok ? [r.item] : [])),
      problems: results.flatMap((r) => (r.ok ? [] : [r])),
    }
  }, [batchText])

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
        showSuccessToast(`已录入 ${result.created} 道题`)
      } else {
        showErrorToast(
          `录入 ${result.created} 道，${result.failed.length} 道被拒（第 ${result.failed
            .map((f) => f.index + 1)
            .join("、")} 行：${result.failed[0]?.reason}）`,
        )
      }
      if (result.created > 0) {
        setBatchText("")
        invalidate()
      }
    },
    onError: (error) => showErrorToast(`批量录入失败：${error.message}`),
  })

  // ── 编辑 / 删除 ──
  const [editing, setEditing] = useState<QuestionBankOut | null>(null)
  const [editForm, setEditForm] = useState({
    text: "",
    translation: "",
    suggested_seconds: 20,
  })
  const [toDelete, setToDelete] = useState<QuestionBankOut | null>(null)

  const openEdit = (row: QuestionBankOut) => {
    setEditing(row)
    setEditForm({
      text: row.text,
      translation: row.translation ?? "",
      suggested_seconds: row.suggested_seconds,
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
        },
      }),
    onSuccess: () => {
      showSuccessToast("题目已更新")
      setEditing(null)
      invalidate()
    },
    onError: (error) => showErrorToast(`更新失败：${error.message}`),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => AdminService.deleteQuestion({ questionId: id }),
    onSuccess: () => {
      showSuccessToast("题目已删除")
      setToDelete(null)
      invalidate()
    },
    onError: (error) => showErrorToast(`删除失败：${error.message}`),
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
          情景问答 · 题目管理
        </h1>
        <p className="text-muted-foreground">
          情景问答的集中管理：跨主题搜索、批量粘贴录入、逐条修改。
          学生每轮练习从对应主题的题目里按序抽取。
        </p>
      </div>

      <details className="rounded-xl border bg-card p-4">
        <summary className="cursor-pointer font-medium text-primary">
          批量录入问答题
        </summary>
        <div className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ClipboardPaste className="size-4" />
                批量录入
              </CardTitle>
              <CardDescription>
                每行一道题，格式「英文题目 | 中文提示 |
                建议秒数」，中文和秒数可省略（默认 20 秒）。
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <Label>主题</Label>
                <Select
                  value={batchTopic}
                  onValueChange={setBatchTopic}
                  disabled={topics.length === 0}
                >
                  <SelectTrigger>
                    <SelectValue
                      placeholder={
                        topics.length === 0
                          ? "还没有主题，先去「问答主题与出题」建一个"
                          : "选择题库主题"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {topics.map((t) => (
                      <SelectItem key={t} value={t}>
                        {t}
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
                aria-label="批量录入题目"
              />
              {batchText.trim() && (
                <div className="text-sm text-muted-foreground">
                  将录入{" "}
                  <span className="font-medium text-foreground">
                    {parsed.items.length}
                  </span>{" "}
                  道题
                  {parsed.problems.length > 0 && (
                    <span className="text-destructive">
                      {" "}
                      · {parsed.problems.length} 行有问题：
                      {parsed.problems
                        .map((p) => `第${p.lineno}行（${p.reason}）`)
                        .join("、")}
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
                  录入{" "}
                  {parsed.items.length > 0 ? `${parsed.items.length} 道题` : ""}
                </LoadingButton>
              </div>
            </CardContent>
          </Card>
        </div>
      </details>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">全部题目</CardTitle>
          <CardDescription>
            共 {rows.length} 条，按主题、序号排列。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Select value={filterTopic} onValueChange={setFilterTopic}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_TOPICS}>全部主题</SelectItem>
                {topics.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
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
                placeholder="搜题目或中文提示…"
                aria-label="搜索题目"
              />
              <Button type="submit" variant="outline">
                搜索
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
              <p>题库加载失败。</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void bankQuery.refetch()}
              >
                重试
              </Button>
            </div>
          ) : rows.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              没有符合条件的题目，换个筛选条件或在上面批量录入。
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>主题</TableHead>
                  <TableHead>题目</TableHead>
                  <TableHead>中文提示</TableHead>
                  <TableHead className="w-16">秒数</TableHead>
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
                          aria-label="编辑题目"
                          onClick={() => openEdit(row)}
                        >
                          <Pencil />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label="删除题目"
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
            <DialogTitle>编辑题目</DialogTitle>
            <DialogDescription>
              修改会即时生效；学生下一轮抽题时使用新内容。
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="q-text">英文题目</Label>
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
              <Label htmlFor="q-translation">中文提示（可选）</Label>
              <Input
                id="q-translation"
                value={editForm.translation}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, translation: e.target.value }))
                }
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="q-seconds">建议秒数（10–60）</Label>
              <Input
                id="q-seconds"
                type="number"
                min={10}
                max={60}
                value={editForm.suggested_seconds}
                onChange={(e) =>
                  setEditForm((f) => ({
                    ...f,
                    suggested_seconds: Number(e.target.value),
                  }))
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>
              取消
            </Button>
            <LoadingButton
              disabled={!editValid}
              loading={updateMutation.isPending}
              onClick={() => updateMutation.mutate()}
            >
              保存
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={toDelete !== null}
        title="删除这道题？"
        description={`「${toDelete?.text ?? ""}」删除后学生抽题不再出现，历史作答保留。此操作不可撤销。`}
        confirmText="删除题目"
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
