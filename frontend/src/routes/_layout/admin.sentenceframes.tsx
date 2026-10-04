import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { MessageSquareQuote, Pencil, Plus, Trash2 } from "lucide-react"
import { useState } from "react"
import { AdminService, ApiError, type SentenceFramePublic } from "@/client"
import { Badge } from "@/components/ui/badge"
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
import { Label } from "@/components/ui/label"
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
  FRAME_PURPOSE_LABELS,
  VOCAB_LEVEL_ORDER,
} from "@/lib/terms"

export const Route = createFileRoute("/_layout/admin/sentenceframes")({
  component: SentenceFramesAdmin,
  head: () => ({
    meta: [{ title: `句型库 / Sentence Frames - ${APP_NAME}` }],
  }),
})

type FrameRow = SentenceFramePublic

const EMPTY_FORM = {
  level: "KET",
  purpose: "opinion",
  exam_kind: "",
  text_en: "",
  text_zh: "",
}

function SentenceFramesAdmin() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const framesQuery = useQuery({
    queryKey: ["admin", "sentence-frames"],
    queryFn: () => AdminService.listSentenceFrames(),
  })
  const frames = framesQuery.data ?? []

  const [filterLevel, setFilterLevel] = useState("")
  const [filterPurpose, setFilterPurpose] = useState("")
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [editing, setEditing] = useState<FrameRow | null>(null)
  const [toDelete, setToDelete] = useState<FrameRow | null>(null)

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "sentence-frames"] })

  const createMutation = useMutation({
    mutationFn: () =>
      AdminService.createSentenceFrame({
        requestBody: {
          level: form.level,
          purpose: form.purpose,
          exam_kind: form.exam_kind || null,
          text_en: form.text_en.trim(),
          text_zh: form.text_zh.trim(),
        },
      }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "句型已创建", en: "Frame created" }))
      invalidate()
      setCreating(false)
      setForm({ ...EMPTY_FORM })
    },
    onError: (error) =>
      showErrorToast(
        error instanceof ApiError
          ? ((error.body as { detail?: string } | undefined)?.detail ??
              t({ zh: "创建失败", en: "Failed to create" }))
          : t({ zh: "创建失败", en: "Failed to create" }),
      ),
  })

  const updateMutation = useMutation({
    mutationFn: (payload: {
      id: string
      requestBody: Record<string, unknown>
    }) =>
      AdminService.updateSentenceFrame({
        frameId: payload.id,
        requestBody: payload.requestBody,
      }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "句型已更新", en: "Frame updated" }))
      invalidate()
      setEditing(null)
    },
    onError: (error) =>
      showErrorToast(
        error instanceof ApiError
          ? ((error.body as { detail?: string } | undefined)?.detail ??
              t({ zh: "更新失败", en: "Failed to update" }))
          : t({ zh: "更新失败", en: "Failed to update" }),
      ),
  })

  const deleteMutation = useMutation({
    mutationFn: (frameId: string) =>
      AdminService.deleteSentenceFrame({ frameId }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "句型已删除", en: "Frame deleted" }))
      invalidate()
      setToDelete(null)
    },
    onError: () =>
      showErrorToast(t({ zh: "删除失败", en: "Failed to delete" })),
  })

  const filtered = frames.filter(
    (frame) =>
      (!filterLevel || frame.level === filterLevel) &&
      (!filterPurpose || frame.purpose === filterPurpose),
  )

  const formValid =
    form.text_en.trim() &&
    form.text_zh.trim() &&
    form.level &&
    form.purpose &&
    // 有题型必配级别（与题型训练一致）
    (!form.exam_kind || form.level)

  const openCreate = () => {
    setForm({ ...EMPTY_FORM })
    setCreating(true)
  }

  const submitDialog = () => {
    if (editing) {
      updateMutation.mutate({
        id: editing.id,
        requestBody: {
          level: form.level,
          purpose: form.purpose,
          exam_kind: form.exam_kind || null,
          text_en: form.text_en.trim(),
          text_zh: form.text_zh.trim(),
        },
      })
    } else {
      createMutation.mutate()
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t({ zh: "句型库", en: "Sentence Frames" })}
        </h1>
        <p className="text-muted-foreground">
          {t({
            zh: "按级别与表达用途分类的可替换句型，供学生口语练习时套用或收藏。",
            en: "Replaceable sentence frames by level and purpose for students to use or favorite during speaking practice.",
          })}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={filterLevel}
          onChange={(e) => setFilterLevel(e.target.value)}
          aria-label={t({ zh: "按级别筛选", en: "Filter by level" })}
          className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
        >
          <option value="">{t({ zh: "全部级别", en: "All levels" })}</option>
          {VOCAB_LEVEL_ORDER.map((level) => (
            <option key={level} value={level}>
              {t(EXAM_LEVEL_LABELS[level])}
            </option>
          ))}
        </select>
        <select
          value={filterPurpose}
          onChange={(e) => setFilterPurpose(e.target.value)}
          aria-label={t({ zh: "按用途筛选", en: "Filter by purpose" })}
          className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
        >
          <option value="">{t({ zh: "全部用途", en: "All purposes" })}</option>
          {Object.entries(FRAME_PURPOSE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {t(label)}
            </option>
          ))}
        </select>
        <Button className="ml-auto" size="sm" onClick={openCreate}>
          <Plus />
          {t({ zh: "新建句型", en: "New Frame" })}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <MessageSquareQuote className="size-4 text-primary" />
            {t({ zh: "全部句型", en: "All frames" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "考试题型留空 = 通用句型（任何考试式题型均推荐）。",
              en: "Leave exam task empty for general frames (recommended for any exam-style task).",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="pb-0">
          {framesQuery.isPending ? (
            <p role="status" className="pb-6 text-sm text-muted-foreground">
              {t({ zh: "正在加载…", en: "Loading…" })}
            </p>
          ) : filtered.length === 0 ? (
            <p className="pb-6 text-sm text-muted-foreground">
              {t({ zh: "还没有句型。", en: "No frames yet." })}
            </p>
          ) : (
            <>
              <p className="pb-3 text-xs text-muted-foreground sm:hidden">
                {t({
                  zh: "横向滑动表格查看完整内容。",
                  en: "Swipe to see all fields.",
                })}
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t({ zh: "级别", en: "Level" })}</TableHead>
                    <TableHead>{t({ zh: "用途", en: "Purpose" })}</TableHead>
                    <TableHead>
                      {t({ zh: "英文句型", en: "English" })}
                    </TableHead>
                    <TableHead>{t({ zh: "中文", en: "Chinese" })}</TableHead>
                    <TableHead>{t({ zh: "题型", en: "Task" })}</TableHead>
                    <TableHead>{t({ zh: "操作", en: "Actions" })}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((frame) => (
                    <TableRow key={frame.id}>
                      <TableCell>
                        <Badge variant="outline">
                          {t(
                            EXAM_LEVEL_LABELS[
                              frame.level as keyof typeof EXAM_LEVEL_LABELS
                            ] ?? { zh: frame.level, en: frame.level },
                          )}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {t(
                          FRAME_PURPOSE_LABELS[frame.purpose] ?? {
                            zh: frame.purpose,
                            en: frame.purpose,
                          },
                        )}
                      </TableCell>
                      <TableCell className="max-w-56 truncate font-medium">
                        {frame.text_en}
                      </TableCell>
                      <TableCell className="max-w-48 truncate text-muted-foreground">
                        {frame.text_zh}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {frame.exam_kind
                          ? t(
                              EXAM_KIND_LABELS[frame.exam_kind] ?? {
                                zh: frame.exam_kind,
                                en: frame.exam_kind,
                              },
                            )
                          : t({ zh: "通用", en: "General" })}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setForm({
                                level: frame.level,
                                purpose: frame.purpose,
                                exam_kind: frame.exam_kind ?? "",
                                text_en: frame.text_en,
                                text_zh: frame.text_zh,
                              })
                              setEditing(frame)
                            }}
                          >
                            <Pencil />
                            {t({ zh: "编辑", en: "Edit" })}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setToDelete(frame)}
                          >
                            <Trash2 />
                            {t({ zh: "删除", en: "Delete" })}
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}
        </CardContent>
      </Card>

      {/* 新建/编辑对话框 */}
      <Dialog
        open={creating || editing !== null}
        onOpenChange={(open) => {
          if (!open) {
            setCreating(false)
            setEditing(null)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editing
                ? t({ zh: "编辑句型", en: "Edit Frame" })
                : t({ zh: "新建句型", en: "New Frame" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "按级别与表达用途分类；学生在考试式练习题下看到推荐并可收藏。",
                en: "Students see recommended frames under exam-style tasks and can favorite them.",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor="frame-level">
                  {t({ zh: "级别", en: "Level" })}
                </Label>
                <select
                  id="frame-level"
                  value={form.level}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, level: e.target.value }))
                  }
                  className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
                >
                  {VOCAB_LEVEL_ORDER.map((level) => (
                    <option key={level} value={level}>
                      {t(EXAM_LEVEL_LABELS[level])}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="frame-purpose">
                  {t({ zh: "表达用途", en: "Purpose" })}
                </Label>
                <select
                  id="frame-purpose"
                  value={form.purpose}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, purpose: e.target.value }))
                  }
                  className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
                >
                  {Object.entries(FRAME_PURPOSE_LABELS).map(
                    ([value, label]) => (
                      <option key={value} value={value}>
                        {t(label)}
                      </option>
                    ),
                  )}
                </select>
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="frame-exam-kind">
                {t({ zh: "关联题型（可选）", en: "Exam task (optional)" })}
              </Label>
              <select
                id="frame-exam-kind"
                value={form.exam_kind}
                onChange={(e) =>
                  setForm((f) => ({ ...f, exam_kind: e.target.value }))
                }
                className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
              >
                <option value="">
                  {t({ zh: "通用（所有题型）", en: "General (all tasks)" })}
                </option>
                {Object.entries(EXAM_KIND_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {t(label)}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="frame-en">
                {t({ zh: "英文句型", en: "English frame" })}
              </Label>
              <Textarea
                id="frame-en"
                rows={2}
                value={form.text_en}
                onChange={(e) =>
                  setForm((f) => ({ ...f, text_en: e.target.value }))
                }
                placeholder="In my opinion, ..."
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="frame-zh">
                {t({ zh: "中文对照", en: "Chinese" })}
              </Label>
              <Textarea
                id="frame-zh"
                rows={2}
                value={form.text_zh}
                onChange={(e) =>
                  setForm((f) => ({ ...f, text_zh: e.target.value }))
                }
                placeholder={t({ zh: "在我看来……", en: "In my opinion, ..." })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setCreating(false)
                setEditing(null)
              }}
            >
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <Button disabled={!formValid} onClick={submitDialog}>
              {t({ zh: "保存", en: "Save" })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认 */}
      <Dialog
        open={toDelete !== null}
        onOpenChange={(open) => {
          if (!open) setToDelete(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "删除这条句型？", en: "Delete this frame?" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: `「${toDelete?.text_en ?? ""}」删除后学生不再看到推荐，历史收藏自动移除。`,
                en: `"${toDelete?.text_en ?? ""}" will no longer be recommended; existing favorites are removed.`,
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setToDelete(null)}>
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <Button
              variant="destructive"
              disabled={deleteMutation.isPending}
              onClick={() => {
                if (toDelete) deleteMutation.mutate(toDelete.id)
              }}
            >
              {t({ zh: "删除", en: "Delete" })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
