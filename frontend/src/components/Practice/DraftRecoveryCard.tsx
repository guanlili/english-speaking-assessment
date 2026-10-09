import { useQueryClient } from "@tanstack/react-query"
import { CloudUpload, Trash2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import type { PlanItem } from "@/client"
import { Button } from "@/components/ui/button"
import type { AttemptSubmitTarget } from "@/hooks/useAttemptSubmit"
import { useI18n } from "@/lib/i18n"
import {
  currentDraftOwner,
  deleteRecordingDraft,
  getRecordingDraft,
  listRecordingDrafts,
  type RecordingDraftMeta,
} from "@/lib/recording-drafts"

interface DraftFailure {
  status?: number
  message?: string
}

/**
 * 未上传录音草稿的恢复入口（批次08B）。
 *
 * - 只列出「当前账号 + 当前课堂」的草稿，用户明确选择才上传/丢弃，
 *   绝不自动上传、不自动切到草稿对应的题目；
 * - 上传走草稿里钉住的原目标（题型/题目/会话/原幂等键）：服务器按幂等键
 *   去重，回包丢失后重传也不会重复创建作答；题目已不在今日计划时只提供丢弃；
 * - 服务器拒绝（考试截止/题窗关闭/题目更换）时结果以服务器为准：显示
 *   原因、保留草稿、不自动重试，由用户决定稍后再试或丢弃。
 */

function formatDraftTime(ts: number, lang: string): string {
  return new Intl.DateTimeFormat(lang === "en" ? "en-US" : "zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(ts))
}

export function DraftRecoveryCard({
  code,
  items,
  submitAsync,
}: {
  code: string
  items: PlanItem[]
  submitAsync: (
    variables: { blob: Blob; duration: number },
    targetOverride?: AttemptSubmitTarget,
  ) => Promise<unknown>
}) {
  const { t, lang } = useI18n()
  const queryClient = useQueryClient()
  const [drafts, setDrafts] = useState<RecordingDraftMeta[] | null>(null)
  const [uploadingKey, setUploadingKey] = useState<string | null>(null)
  const [failures, setFailures] = useState<Record<string, DraftFailure>>({})
  // 丢弃两步确认：第一次点击变成「确认丢弃」，3 秒内再点才删除
  const [discardArmedKey, setDiscardArmedKey] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const owner = currentDraftOwner()
    if (!owner) {
      setDrafts([])
      return
    }
    setDrafts(await listRecordingDrafts(owner, code))
  }, [code])

  useEffect(() => {
    void refresh()
  }, [refresh])

  if (drafts === null || drafts.length === 0) return null

  const uploadDraft = async (draft: RecordingDraftMeta) => {
    setUploadingKey(draft.key)
    setFailures((prev) => {
      const next = { ...prev }
      delete next[draft.key]
      return next
    })
    try {
      const record = await getRecordingDraft(draft.key)
      if (!record) {
        // 已被清理（过期/TTL）：直接刷新列表
        await refresh()
        return
      }
      await submitAsync(
        { blob: record.blob, duration: record.durationS },
        {
          itemType: draft.itemType,
          itemId: draft.itemId,
          ...(draft.sessionId ? { sessionId: draft.sessionId } : {}),
          idempotencyKey: draft.idempotencyKey,
        },
      )
      // 服务器已接受：删草稿，进度交给 today 轮询（评分 pending 不重复上传）
      await deleteRecordingDraft(draft.key)
      toast.success(
        t({
          zh: "这段录音已上传，评分完成后可见反馈",
          en: "Recording uploaded. Feedback will appear once scoring finishes.",
        }),
      )
      await refresh()
      void queryClient.invalidateQueries({
        queryKey: ["classroom", code, "today"],
      })
    } catch (err) {
      // 保留草稿、不自动重试；以服务器结果为准
      const e = err as { status?: number; body?: { detail?: unknown } }
      const detail =
        typeof e?.body?.detail === "string" ? e.body.detail : undefined
      setFailures((prev) => ({
        ...prev,
        [draft.key]: { status: e?.status, message: detail },
      }))
    } finally {
      setUploadingKey(null)
    }
  }

  const discardDraft = async (draft: RecordingDraftMeta) => {
    if (discardArmedKey !== draft.key) {
      setDiscardArmedKey(draft.key)
      window.setTimeout(
        () =>
          setDiscardArmedKey((armed) => (armed === draft.key ? null : armed)),
        3000,
      )
      return
    }
    setDiscardArmedKey(null)
    await deleteRecordingDraft(draft.key)
    await refresh()
  }

  return (
    <section
      aria-label={t({
        zh: "未上传的录音草稿",
        en: "Unuploaded recording drafts",
      })}
      className="rounded-xl border border-amber-500/40 bg-amber-500/5 px-4 py-3"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
        <CloudUpload className="size-4 text-amber-600" aria-hidden />
        {t({
          zh: "有未上传的录音草稿",
          en: "You have unuploaded recording drafts",
        })}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {t({
          zh: "刷新或断网前录好但没传成功的录音会暂存在这台设备上（24 小时后自动清除）。是否上传由你决定；只在本设备保存，不上传不会计分。",
          en: "Recordings that finished but failed to upload are kept on this device (auto-cleared after 24 hours). Uploading is your choice; drafts stay local and are never scored until uploaded.",
        })}
      </p>
      <ul className="mt-3 grid gap-2">
        {drafts.map((draft) => {
          const item = items.find((i) => i.id === draft.itemId)
          const failure = failures[draft.key]
          const rejected = failure?.status !== undefined && failure.status < 500
          return (
            <li
              key={draft.key}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-background px-3 py-2.5"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">
                  {item ? (
                    item.text
                  ) : (
                    <span className="text-muted-foreground">
                      {t({
                        zh: "本题已不在今天的练习中（可能换题或老师重新发布）",
                        en: "This item is no longer in today's practice (content changed or your teacher republished)",
                      })}
                    </span>
                  )}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {t({ zh: "时长", en: "Length" })}{" "}
                  {Math.round(draft.durationS)}s ·{" "}
                  {t({ zh: "录于", en: "Recorded" })}{" "}
                  {formatDraftTime(draft.createdAt, lang)}
                </p>
                {failure && (
                  <p
                    role="alert"
                    className={
                      rejected
                        ? "mt-1 text-xs text-destructive"
                        : "mt-1 text-xs text-muted-foreground"
                    }
                  >
                    {rejected
                      ? t({
                          zh: "服务器没有接受这段录音（可能考试已截止或题目已更换），结果以服务器为准；可稍后再试或丢弃",
                          en: "The server did not accept this recording (the exam may have closed or the item changed). The server's decision is final — retry later or discard it.",
                        })
                      : t({
                          zh: "上传失败，草稿已保留，可稍后再试",
                          en: "Upload failed. The draft is kept — you can retry later.",
                        })}
                    {failure.message ? `（${failure.message}）` : ""}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {item && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-11"
                    disabled={uploadingKey !== null}
                    onClick={() => void uploadDraft(draft)}
                  >
                    {uploadingKey === draft.key
                      ? t({ zh: "上传中…", en: "Uploading…" })
                      : t({ zh: "上传这段录音", en: "Upload" })}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-11 text-muted-foreground"
                  disabled={uploadingKey !== null}
                  onClick={() => void discardDraft(draft)}
                >
                  <Trash2 className="size-4" aria-hidden />
                  {discardArmedKey === draft.key
                    ? t({ zh: "确认丢弃", en: "Confirm discard" })
                    : t({ zh: "丢弃", en: "Discard" })}
                </Button>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export default DraftRecoveryCard
