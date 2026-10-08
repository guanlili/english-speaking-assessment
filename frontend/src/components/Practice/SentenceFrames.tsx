import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Star } from "lucide-react"
import type { PlanItem } from "@/client"
import { ClassesService } from "@/client"
import { useI18n } from "@/lib/i18n"
import { FRAME_PURPOSE_LABELS } from "@/lib/terms"

/**
 * 可替换句型（PR B）：按表达用途分组，单条可收藏/取消，
 * 收藏挂课堂档案跨设备可见。
 */
export default function SentenceFrames({
  frames,
  code,
  todayQueryKey,
}: {
  frames: NonNullable<PlanItem["frames"]>
  code: string
  todayQueryKey: readonly unknown[]
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  // 句型收藏：按单条表达收藏/取消，挂课堂档案跨设备可见
  const frameFavorite = useMutation({
    mutationFn: (frameId: string) =>
      ClassesService.addFrameFavorite({
        code: code.toUpperCase(),
        requestBody: { frame_id: frameId },
      }),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: todayQueryKey }),
  })
  const unfavorite = useMutation({
    mutationFn: (frameId: string) =>
      ClassesService.removeFrameFavorite({
        code: code.toUpperCase(),
        frameId,
      }),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: todayQueryKey }),
  })

  return (
    <div className="rounded-xl border border-dashed border-primary/30 bg-secondary/30 p-4">
      <p className="text-xs font-semibold tracking-wide text-primary">
        {t({
          zh: "可替换句型 · 套用或改成你自己的表达",
          en: "Sentence frames · use as-is or make them yours",
        })}
      </p>
      <div className="mt-3 space-y-2">
        {frames.map((frame) => (
          <div
            key={frame.id}
            className="flex items-start justify-between gap-2 rounded-lg bg-background px-3 py-2"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{frame.text_en}</p>
              <p className="truncate text-xs text-muted-foreground">
                {frame.text_zh}
                {" · "}
                {t(
                  FRAME_PURPOSE_LABELS[frame.purpose] ?? {
                    zh: frame.purpose,
                    en: frame.purpose,
                  },
                )}
              </p>
            </div>
            <button
              type="button"
              aria-pressed={frame.favorited}
              aria-label={
                frame.favorited
                  ? t({ zh: "取消收藏", en: "Remove from favorites" })
                  : t({ zh: "收藏这条句型", en: "Favorite this frame" })
              }
              disabled={frameFavorite.isPending}
              onClick={() => {
                if (frame.favorited) {
                  unfavorite.mutate(frame.id)
                } else {
                  frameFavorite.mutate(frame.id)
                }
              }}
              className="shrink-0 p-1 text-muted-foreground transition-colors hover:text-primary"
            >
              <Star
                className={
                  frame.favorited
                    ? "size-4 fill-amber-400 text-amber-400"
                    : "size-4"
                }
              />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
