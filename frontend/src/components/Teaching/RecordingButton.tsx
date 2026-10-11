import { Pause, Volume2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { fetchAudioObjectUrl } from "@/lib/attempt-audio"
import { useI18n } from "@/lib/i18n"

/** Keep playback beside its answer, including an explicit retry if autoplay is blocked. */
export function RecordingButton({
  attemptId,
  label,
}: {
  attemptId: string
  label: string
}) {
  const { t } = useI18n()
  const audioRef = useRef<HTMLAudioElement>(null)
  const urlRef = useRef<string | null>(null)
  const mounted = useRef(true)
  const [loading, setLoading] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState(false)
  useEffect(() => {
    mounted.current = true
    const audio = audioRef.current
    return () => {
      mounted.current = false
      audio?.pause()
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    }
  }, [])
  const play = async () => {
    const audio = audioRef.current
    if (!audio || loading) return
    if (!audio.paused) {
      audio.pause()
      return
    }
    setLoading(true)
    setError(false)
    // Also cancels an older pending request from starting out of order.
    document.dispatchEvent(
      new CustomEvent("teacher-recording-selected", { detail: audio }),
    )
    try {
      if (!urlRef.current) {
        const url = await fetchAudioObjectUrl(attemptId)
        if (!mounted.current) {
          URL.revokeObjectURL(url)
          return
        }
        urlRef.current = url
        audio.src = url
      }
      if (!selected.current) return
      if (audio.error) audio.load()
      await audio.play()
    } catch {
      if (mounted.current && selected.current) setError(true)
    } finally {
      if (mounted.current) setLoading(false)
    }
  }
  const selected = useRef(false)
  useEffect(() => {
    const onSelect = (event: Event) => {
      selected.current = (event as CustomEvent).detail === audioRef.current
      if (!selected.current) audioRef.current?.pause()
    }
    document.addEventListener("teacher-recording-selected", onSelect)
    return () =>
      document.removeEventListener("teacher-recording-selected", onSelect)
  }, [])
  return (
    <div className="space-y-1">
      <Button
        variant="ghost"
        size="sm"
        className="min-h-11"
        disabled={loading}
        aria-label={label}
        aria-pressed={playing}
        onClick={(event) => {
          event.stopPropagation()
          void play()
        }}
      >
        {playing ? (
          <Pause className="size-4" />
        ) : (
          <Volume2 className="size-4" />
        )}
        {t(
          loading
            ? { zh: "加载录音…", en: "Loading recording…" }
            : playing
              ? { zh: "暂停录音", en: "Pause recording" }
              : { zh: "听录音", en: "Listen to recording" },
        )}
      </Button>
      {error && (
        <p role="alert" className="max-w-56 text-xs text-destructive">
          {t({
            zh: "播放未成功，请再次点击「听录音」重试。",
            en: "Playback failed. Click Listen to recording again to retry.",
          })}
        </p>
      )}
      <audio
        ref={audioRef}
        preload="none"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => {
          if (selected.current) setError(true)
        }}
      >
        <track kind="captions" />
      </audio>
    </div>
  )
}
