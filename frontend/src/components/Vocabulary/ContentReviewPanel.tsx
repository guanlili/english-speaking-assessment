import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Loader2, Pencil, Search, XCircle } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import {
  ApiError,
  type VocabularyReviewItem,
  VocabularyService,
  type VocabularyWordPublic,
} from "@/client"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { WordEditDialog } from "@/components/Vocabulary/WordEditDialog"
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"
import {
  CODE_REVIEW_STATE_CONFLICT,
  parseDetailCount,
  reviewStatusLabel,
  SOURCE_FILTER_OPTIONS,
  sourceLabel,
  type WordSource,
} from "@/lib/vocabContentReview"

type StatusFilter = "pending" | "rejected" | "all"

interface ReviewActionDialog {
  action: "approve" | "reject"
  ids: string[]
}

/**
 * 内容审核面板（管理员词库页 / 教师课堂词库审核 tab 共用）。
 *
 * - 教师模式传 classroomId，后端按本人班级库收口；admin 模式看全校；
 * - 批量与逐条审核：拒绝必须填意见；通过意见可选；
 * - 409 状态冲突 / 403 / 网络错误都明确 toast，不静默；
 * - readonly（平台运营只读）下不展示审核动作，学校 UI 不接入运营入口。
 */
export function ContentReviewPanel({
  classroomId,
  bookId,
  readonly = false,
  onPendingCountChange,
  onReviewed,
}: {
  classroomId?: string | null
  bookId?: string | null
  readonly?: boolean
  onPendingCountChange?: (pending: number) => void
  onReviewed?: () => void
}) {
  const { t, lang } = useI18n()
  const queryClient = useQueryClient()

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending")
  const [sourceFilter, setSourceFilter] = useState<"" | WordSource>("")
  const [keyword, setKeyword] = useState("")
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [actionDialog, setActionDialog] = useState<ReviewActionDialog | null>(
    null,
  )
  const [noteText, setNoteText] = useState("")
  const [noteError, setNoteError] = useState<string | null>(null)
  const [editingWord, setEditingWord] = useState<VocabularyWordPublic | null>(
    null,
  )
  const [editLoading, setEditLoading] = useState(false)

  const reviewsQuery = useQuery({
    queryKey: [
      "vocab-review",
      { classroomId, bookId, statusFilter, sourceFilter, keyword },
    ],
    queryFn: () =>
      VocabularyService.listVocabularyReviews({
        status: statusFilter === "all" ? null : statusFilter,
        source: sourceFilter || null,
        book_id: bookId ?? null,
        classroom_id: classroomId ?? null,
        q: keyword.trim() || null,
        limit: 200,
      }),
  })

  const items = reviewsQuery.data?.items ?? []
  const pendingCount = reviewsQuery.data?.pending_count ?? 0

  useEffect(() => {
    onPendingCountChange?.(pendingCount)
  }, [pendingCount, onPendingCountChange])

  const refreshQueue = () => {
    void queryClient.invalidateQueries({ queryKey: ["vocab-review"] })
    onReviewed?.()
  }

  const reviewMutation = useMutation({
    mutationFn: (payload: {
      action: "approve" | "reject"
      ids: string[]
      note: string | null
    }) =>
      VocabularyService.reviewVocabularyWords({
        vocabularyReviewActionRequest: {
          word_ids: payload.ids,
          action: payload.action,
          note: payload.note,
        },
      }),
    onSuccess: (result, payload) => {
      toast.success(
        payload.action === "approve"
          ? t({
              zh: `已通过 ${result.updated} 条词条。`,
              en: `Approved ${result.updated} word entries.`,
            })
          : t({
              zh: `已拒绝 ${result.updated} 条词条。`,
              en: `Rejected ${result.updated} word entries.`,
            }),
      )
      setSelected(new Set())
      setActionDialog(null)
      setNoteText("")
      setNoteError(null)
      refreshQueue()
    },
    onError: (error) => {
      if (!(error instanceof ApiError)) {
        toast.error(
          t({
            zh: "网络异常，审核操作未完成，请检查连接后重试。",
            en: "Network error — review action didn't go through. Check your connection and retry.",
          }),
        )
        return
      }
      const detail =
        typeof error.body === "object" && error.body !== null
          ? ((error.body as { detail?: unknown }).detail ?? error.message)
          : error.message
      if (error.status === 409) {
        const conflictCount = parseDetailCount(
          detail,
          CODE_REVIEW_STATE_CONFLICT,
        )
        toast.error(
          conflictCount !== null
            ? t({
                zh: `${conflictCount} 条词条当前已不是待审状态（可能刚被处理），队列已刷新，请重新选择。`,
                en: `${conflictCount} entries are no longer pending (handled just now). The queue refreshed — please reselect.`,
              })
            : t({
                zh: "词条状态冲突，请刷新队列后重试。",
                en: "Word state conflict — refresh the queue and retry.",
              }),
        )
        refreshQueue()
        return
      }
      if (error.status === 403) {
        toast.error(
          t({
            zh: "没有权限审核这些词条（仅可审核本人班级或本校词条）。",
            en: "No permission to review these words (your own class or school only).",
          }),
        )
        return
      }
      toast.error(
        t({
          zh: "审核失败，请重试。",
          en: "Review failed — please retry.",
        }),
      )
    },
  })

  const openActionDialog = (action: "approve" | "reject", ids: string[]) => {
    if (ids.length === 0) return
    setActionDialog({ action, ids })
    setNoteText("")
    setNoteError(null)
  }

  const submitAction = () => {
    if (!actionDialog) return
    const note = noteText.trim()
    if (actionDialog.action === "reject" && note.length === 0) {
      setNoteError(
        t({
          zh: "拒绝必须填写审核意见。",
          en: "A note is required when rejecting.",
        }),
      )
      return
    }
    reviewMutation.mutate({
      action: actionDialog.action,
      ids: actionDialog.ids,
      note: note.length > 0 ? note : null,
    })
  }

  const toggleAll = (checked: boolean) => {
    setSelected(
      checked ? new Set(items.map((item) => item.word_id)) : new Set(),
    )
  }

  const toggleOne = (id: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const openEdit = async (item: VocabularyReviewItem) => {
    if (!item.book_id) {
      toast.error(
        t({
          zh: "缺少词库归属，无法打开编辑。",
          en: "No book attached to this entry — can't open the editor.",
        }),
      )
      return
    }
    setEditLoading(true)
    try {
      const book = await VocabularyService.readBook({
        book_id: item.book_id,
      })
      const found = book.words?.find((word) => word.id === item.word_id)
      if (!found) {
        toast.error(
          t({
            zh: "词条已不在该词库，请刷新后重试。",
            en: "The entry is no longer in this book — refresh and retry.",
          }),
        )
        return
      }
      setEditingWord(found)
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        toast.error(
          t({
            zh: "没有权限查看这个词库。",
            en: "No permission to view this book.",
          }),
        )
      } else {
        toast.error(
          t({
            zh: "加载词条失败，请重试。",
            en: "Couldn't load the word — please retry.",
          }),
        )
      }
    } finally {
      setEditLoading(false)
    }
  }

  const statusOptions: Array<{ value: StatusFilter; label: string }> = [
    { value: "pending", label: t({ zh: "待审", en: "Pending" }) },
    { value: "rejected", label: t({ zh: "已拒绝", en: "Rejected" }) },
    { value: "all", label: t({ zh: "全部", en: "All" }) },
  ]

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            {t({ zh: "词条审核", en: "Content Review" })}
            <Badge
              variant="secondary"
              aria-label={t({ zh: "待审数量", en: "Pending" })}
            >
              {t({ zh: `待审 ${pendingCount}`, en: `${pendingCount} pending` })}
            </Badge>
          </CardTitle>
          <CardDescription>
            {t({
              zh: "新导入、AI 草稿与教师录入的词条先进入待审；通过后才可发布给学生。",
              en: "New imports, AI drafts and teacher entries start pending; only approved words can be published.",
            })}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 筛选行 */}
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label={t({ zh: "状态筛选", en: "Filter by status" })}
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as StatusFilter)
            }
            className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
          >
            {statusOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            aria-label={t({ zh: "来源筛选", en: "Filter by source" })}
            value={sourceFilter}
            onChange={(event) =>
              setSourceFilter(event.target.value as "" | WordSource)
            }
            className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground"
          >
            <option value="">{t({ zh: "全部来源", en: "All sources" })}</option>
            {SOURCE_FILTER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.label)}
              </option>
            ))}
          </select>
          <div className="relative min-w-40 flex-1 sm:max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder={t({
                zh: "按单词 / 释义搜索…",
                en: "Search word or meaning…",
              })}
              aria-label={t({ zh: "关键词搜索", en: "Keyword search" })}
              className="h-11 pl-9 text-base"
            />
          </div>
        </div>

        {/* 批量操作条 */}
        {!readonly && items.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={items.length > 0 && selected.size === items.length}
                onChange={(event) => toggleAll(event.target.checked)}
                className="size-4 accent-[var(--primary)]"
                aria-label={t({ zh: "全选", en: "Select all" })}
              />
              {t({
                zh: `已选 ${selected.size} 条`,
                en: `${selected.size} selected`,
              })}
            </label>
            <Button
              variant="outline"
              size="sm"
              disabled={selected.size === 0 || reviewMutation.isPending}
              onClick={() => openActionDialog("approve", Array.from(selected))}
            >
              <CheckCircle2 />
              {t({ zh: "批量通过", en: "Approve all" })}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={selected.size === 0 || reviewMutation.isPending}
              onClick={() => openActionDialog("reject", Array.from(selected))}
            >
              <XCircle />
              {t({ zh: "批量拒绝", en: "Reject all" })}
            </Button>
          </div>
        )}

        {/* 队列表格 */}
        {reviewsQuery.isPending ? (
          <div
            role="status"
            className="flex items-center gap-2 py-8 text-sm text-muted-foreground"
          >
            <Loader2 className="size-4 animate-spin" />
            {t({ zh: "正在加载审核队列…", en: "Loading review queue…" })}
          </div>
        ) : items.length === 0 ? (
          <p
            role="status"
            className="py-8 text-center text-sm text-muted-foreground"
          >
            {t({
              zh: "当前筛选下没有词条。",
              en: "No entries match the current filters.",
            })}
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b bg-secondary/50 text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium">
                    {t({ zh: "单词", en: "Word" })}
                  </th>
                  <th className="px-3 py-2 font-medium">
                    {t({ zh: "词性", en: "POS" })}
                  </th>
                  <th className="px-3 py-2 font-medium">
                    {t({ zh: "释义", en: "Meaning" })}
                  </th>
                  <th className="px-3 py-2 font-medium">
                    {t({ zh: "来源", en: "Source" })}
                  </th>
                  <th className="px-3 py-2 font-medium">
                    {t({ zh: "状态", en: "Status" })}
                  </th>
                  <th className="px-3 py-2 font-medium">
                    {t({ zh: "词库 / 意见", en: "Book / Note" })}
                  </th>
                  {!readonly && (
                    <th className="px-3 py-2 font-medium">
                      {t({ zh: "操作", en: "Actions" })}
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.word_id} className="border-b last:border-b-0">
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        {!readonly && (
                          <input
                            type="checkbox"
                            checked={selected.has(item.word_id)}
                            onChange={(event) =>
                              toggleOne(item.word_id, event.target.checked)
                            }
                            className="size-4 accent-[var(--primary)]"
                            aria-label={t({
                              zh: `选择 ${item.headword}`,
                              en: `Select ${item.headword}`,
                            })}
                          />
                        )}
                        <span className="font-semibold">{item.headword}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">
                      {item.part_of_speech ?? "–"}
                    </td>
                    <td className="max-w-56 px-3 py-2.5">
                      <span className="line-clamp-2">{item.meaning_zh}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge
                        variant={item.source === "ai" ? "default" : "outline"}
                      >
                        {t(sourceLabel(item.source))}
                      </Badge>
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge
                        variant={
                          item.review_status === "approved"
                            ? "secondary"
                            : item.review_status === "rejected"
                              ? "destructive"
                              : "outline"
                        }
                      >
                        {t(reviewStatusLabel(item.review_status))}
                      </Badge>
                    </td>
                    <td className="max-w-56 px-3 py-2.5">
                      <div className="text-xs text-muted-foreground">
                        {item.book_title ?? "–"}
                      </div>
                      {item.review_note && (
                        <div className="mt-0.5 line-clamp-2 text-xs">
                          {item.review_note}
                        </div>
                      )}
                      {item.reviewed_at && (
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {formatDateTime(item.reviewed_at, lang)}
                        </div>
                      )}
                    </td>
                    {!readonly && (
                      <td className="px-3 py-2.5">
                        <div className="flex flex-wrap gap-1.5">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={reviewMutation.isPending}
                            onClick={() =>
                              openActionDialog("approve", [item.word_id])
                            }
                          >
                            <CheckCircle2 />
                            {t({ zh: "通过", en: "Approve" })}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={reviewMutation.isPending}
                            onClick={() =>
                              openActionDialog("reject", [item.word_id])
                            }
                          >
                            <XCircle />
                            {t({ zh: "拒绝", en: "Reject" })}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={editLoading}
                            onClick={() => void openEdit(item)}
                          >
                            <Pencil />
                            {t({ zh: "编辑", en: "Edit" })}
                          </Button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>

      {/* 审核意见弹窗：拒绝必填，通过可选 */}
      <Dialog
        open={actionDialog !== null}
        onOpenChange={(next) => {
          if (!next) {
            setActionDialog(null)
            setNoteError(null)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {actionDialog?.action === "approve"
                ? t({ zh: "通过词条", en: "Approve entries" })
                : t({ zh: "拒绝词条", en: "Reject entries" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: `本次操作 ${actionDialog?.ids.length ?? 0} 条词条；整批全有或全无，每条留一条审核记录。`,
                en: `${actionDialog?.ids.length ?? 0} entries in this action; all-or-nothing, one audit record per entry.`,
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="review-note">
              {actionDialog?.action === "reject"
                ? t({ zh: "审核意见（必填）", en: "Review note (required)" })
                : t({ zh: "审核意见（可选）", en: "Review note (optional)" })}
            </Label>
            <Textarea
              id="review-note"
              value={noteText}
              onChange={(event) => {
                setNoteText(event.target.value)
                setNoteError(null)
              }}
              maxLength={512}
              className="min-h-20 text-base"
              placeholder={t({
                zh: "如：释义不准确 / 例句缺少原词…",
                en: "e.g. meaning inaccurate / example missing the word…",
              })}
            />
            {noteError && (
              <p role="alert" className="text-sm text-destructive">
                {noteError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setActionDialog(null)
                setNoteError(null)
              }}
            >
              {t({ zh: "取消", en: "Cancel" })}
            </Button>
            <Button disabled={reviewMutation.isPending} onClick={submitAction}>
              {reviewMutation.isPending ? (
                <Loader2 className="animate-spin" />
              ) : null}
              {actionDialog?.action === "approve"
                ? t({ zh: "确认通过", en: "Approve" })
                : t({ zh: "确认拒绝", en: "Reject" })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <WordEditDialog
        word={editingWord}
        onClose={() => setEditingWord(null)}
        onSaved={() => {
          setEditingWord(null)
          refreshQueue()
          toast.success(t({ zh: "词条已保存。", en: "Word entry saved." }))
          void queryClient.invalidateQueries({ queryKey: ["vocab-teacher"] })
          void queryClient.invalidateQueries({ queryKey: ["admin", "vocab"] })
          void queryClient.invalidateQueries({ queryKey: ["vocab-review"] })
        }}
      />
    </Card>
  )
}
