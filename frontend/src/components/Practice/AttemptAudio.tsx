import { useQuery } from "@tanstack/react-query"
import { useEffect } from "react"
import { fetchAudioObjectUrl } from "@/lib/attempt-audio"
import { useI18n } from "@/lib/i18n"

interface AttemptAudioProps {
  attemptId: string
  className?: string
  preload?: "none" | "metadata" | "auto"
}

/**
 * 受保护作答录音的统一播放器（学生/教师同一路径）：
 * JWT 走 Authorization 头取回 blob，卸载时释放 objectURL。
 * gcTime=0：卸载即弃缓存，下次挂载重新取新 URL——
 * 缓存里的 URL 已随上次卸载被 revoke，复用会变成不可播放的死链。
 */
export default function AttemptAudio({
  attemptId,
  className,
  preload = "none",
}: AttemptAudioProps) {
  const { t } = useI18n()
  const srcQuery = useQuery({
    queryKey: ["attempt-audio", attemptId],
    queryFn: () => fetchAudioObjectUrl(attemptId),
    staleTime: Infinity,
    gcTime: 0,
    retry: 1,
  })

  const objectUrl = srcQuery.data ?? null

  useEffect(() => {
    return () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
      }
    }
  }, [objectUrl])

  if (srcQuery.isPending) {
    return (
      <span className="text-xs text-muted-foreground">
        {t({ zh: "加载录音…", en: "Loading recording…" })}
      </span>
    )
  }
  if (srcQuery.isError || !objectUrl) {
    return (
      <button
        type="button"
        className="text-xs text-destructive underline-offset-2 hover:underline"
        onClick={() => void srcQuery.refetch()}
      >
        {t({
          zh: "录音加载失败，点击重试",
          en: "Failed to load recording — tap to retry",
        })}
      </button>
    )
  }
  return (
    <audio
      controls
      preload={preload}
      src={objectUrl}
      className={className}
      onClick={(e) => e.stopPropagation()}
    >
      <track kind="captions" />
    </audio>
  )
}
