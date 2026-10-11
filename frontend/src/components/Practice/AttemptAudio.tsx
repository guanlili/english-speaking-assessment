import { useQuery } from "@tanstack/react-query"
import { Pause, Play } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { fetchAudioBlob } from "@/lib/attempt-audio"
import { useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"

interface AttemptAudioProps {
  attemptId: string
  className?: string
  preload?: "none" | "metadata" | "auto"
  durationSeconds?: number
}

function timeLabel(seconds: number) {
  return `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`
}

export default function AttemptAudio(props: AttemptAudioProps) {
  // A new attempt must not reuse another recording's position or pending play.
  return <AttemptAudioPlayer key={props.attemptId} {...props} />
}

/** Cache bytes; each mounted player owns and releases its own URL. */
function AttemptAudioPlayer({
  attemptId,
  className,
  preload = "metadata",
  durationSeconds = 0,
}: AttemptAudioProps) {
  const { t } = useI18n()
  const audioRef = useRef<HTMLAudioElement>(null)
  const mounted = useRef(false)
  const blobRef = useRef<Blob | undefined>(undefined)
  const [ready, setReady] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [position, setPosition] = useState(0)
  const [duration, setDuration] = useState(
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? durationSeconds
      : 0,
  )
  const [playError, setPlayError] = useState(false)
  const srcQuery = useQuery({
    queryKey: ["attempt-audio-blob", attemptId],
    queryFn: () => fetchAudioBlob(attemptId),
    staleTime: Infinity,
    gcTime: 0,
    retry: 1,
  })
  const blob = srcQuery.data
  useEffect(() => {
    const audio = audioRef.current
    mounted.current = true
    blobRef.current = blob
    if (!audio || !blob)
      return () => {
        mounted.current = false
      }
    const url = URL.createObjectURL(blob)
    audio.src = url
    audio.muted = false
    audio.volume = 1
    audio.load()
    setReady(true)
    setPlaying(false)
    setPosition(0)
    setPlayError(false)
    return () => {
      mounted.current = false
      blobRef.current = undefined
      audio.pause()
      audio.removeAttribute("src")
      audio.load()
      URL.revokeObjectURL(url)
    }
  }, [blob])

  const syncDuration = () => {
    const value = audioRef.current?.duration
    if (value && Number.isFinite(value)) setDuration(value)
  }
  const loadDuration = () => {
    const audio = audioRef.current
    if (!audio) return
    if (Number.isFinite(audio.duration) && audio.duration > 0) {
      syncDuration()
      return
    }
    // MediaRecorder WebM can omit duration. Decode bytes for the timeline;
    // never seek to a huge timestamp, which can leave the first play at EOF.
    if (duration > 0 || !blob) return
    void blob
      .arrayBuffer()
      .then((bytes) =>
        new OfflineAudioContext(1, 1, 48000).decodeAudioData(bytes),
      )
      .then((decoded) => {
        if (
          mounted.current &&
          blobRef.current === blob &&
          Number.isFinite(decoded.duration)
        )
          setDuration(decoded.duration)
      })
      .catch(() => {
        /* Playback may still be supported; retain the visible disabled timeline. */
      })
  }
  const toggle = () => {
    const audio = audioRef.current
    if (!audio || !ready) return
    if (!audio.paused) {
      audio.pause()
      return
    }
    setPlayError(false)
    if (audio.error) audio.load()
    if (audio.ended) audio.currentTime = 0
    const source = audio.src
    // play() is invoked synchronously inside the user's click, including Safari.
    void audio.play().catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") return
      if (mounted.current && audio.src === source) {
        setPlaying(false)
        setPlayError(true)
      }
    })
  }
  return (
    <div className={cn("min-h-24 w-full min-w-0 space-y-1", className)}>
      <audio
        ref={audioRef}
        preload={preload}
        onLoadedMetadata={loadDuration}
        onDurationChange={syncDuration}
        onPlaying={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={() => {
          const value = audioRef.current?.currentTime ?? 0
          if (Number.isFinite(value)) setPosition(value)
        }}
        onError={() => {
          if (mounted.current && blobRef.current) {
            setPlaying(false)
            setPlayError(true)
          }
        }}
      >
        <track kind="captions" />
      </audio>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          type="button"
          variant="secondary"
          className="min-h-11"
          disabled={!ready || srcQuery.isPending}
          onClick={(event) => {
            event.stopPropagation()
            toggle()
          }}
          aria-pressed={playing}
        >
          {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
          {t(
            srcQuery.isPending
              ? { zh: "加载录音…", en: "Loading recording…" }
              : playing
                ? { zh: "暂停录音", en: "Pause recording" }
                : { zh: "播放录音", en: "Play recording" },
          )}
        </Button>
        <span className="text-xs tabular-nums text-muted-foreground">
          {timeLabel(position)} / {duration > 0 ? timeLabel(duration) : "–"}
        </span>
      </div>
      <input
        type="range"
        onClick={(event) => event.stopPropagation()}
        aria-label={t({
          zh: "录音播放进度",
          en: "Recording playback progress",
        })}
        min={0}
        max={duration || 1}
        step={0.1}
        value={Math.min(position, duration || 1)}
        disabled={!ready || duration <= 0}
        className="block h-11 w-full min-w-0 cursor-pointer accent-primary disabled:cursor-default"
        onChange={(event) => {
          const audio = audioRef.current
          if (audio) {
            const next = Number(event.target.value)
            audio.currentTime = next
            setPosition(next)
          }
        }}
      />
      {(srcQuery.isError || playError) && (
        <div role="alert" className="text-sm text-destructive">
          <p>
            {t(
              srcQuery.isError
                ? { zh: "录音加载失败。", en: "Failed to load recording." }
                : {
                    zh: "录音播放失败，请重试。",
                    en: "Recording playback failed. Please retry.",
                  },
            )}
          </p>
          <Button
            type="button"
            variant="outline"
            className="mt-1 min-h-11"
            onClick={(event) => {
              event.stopPropagation()
              setPlayError(false)
              void srcQuery.refetch()
            }}
          >
            {t({ zh: "重新加载录音", en: "Reload recording" })}
          </Button>
        </div>
      )}
    </div>
  )
}
