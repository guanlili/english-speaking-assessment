import { useQuery } from "@tanstack/react-query"
import { attemptAudioUrl, fetchAudioObjectUrl } from "@/lib/attempt-audio"

interface AttemptAudioProps {
  attemptId: string
  /** 学生回放传入班凭证；教师面板留空，走 Authorization 头取回 */
  studentToken?: string | null
  className?: string
  preload?: "none" | "metadata" | "auto"
}

/**
 * 受保护作答录音的统一播放器：
 * - 学生：凭证进 query，浏览器原生流式播放；
 * - 教师/管理员：JWT 走 header，先取回 blob 再交给 <audio>。
 * 两端都不靠“知道 UUID”就能听（后端校验身份/归属）。
 */
export default function AttemptAudio({
  attemptId,
  studentToken,
  className,
  preload = "none",
}: AttemptAudioProps) {
  const srcQuery = useQuery({
    queryKey: ["attempt-audio", attemptId, studentToken ? "student" : "staff"],
    queryFn: () =>
      studentToken
        ? attemptAudioUrl(attemptId, studentToken)
        : fetchAudioObjectUrl(attemptId),
    staleTime: Infinity,
    gcTime: 15 * 60_000,
    retry: 1,
  })

  if (srcQuery.isPending) {
    return <span className="text-xs text-muted-foreground">加载录音…</span>
  }
  if (srcQuery.isError || !srcQuery.data) {
    return (
      <button
        type="button"
        className="text-xs text-destructive underline-offset-2 hover:underline"
        onClick={() => void srcQuery.refetch()}
      >
        录音加载失败，点击重试
      </button>
    )
  }
  return (
    <audio
      controls
      preload={preload}
      src={srcQuery.data}
      className={className}
      onClick={(e) => e.stopPropagation()}
    >
      <track kind="captions" />
    </audio>
  )
}
