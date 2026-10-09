/**
 * 限听版标准音：听句复述题专用。每次播放先到服务端计数（防刷真源），
 * 次数用完禁用；replay_limit=0 不限。朗读/问答仍用不限次 SpeakButton。
 */
import { Volume2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { ApiError, ClassesService } from "@/client"
import { Button } from "@/components/ui/button"
import type { BiString } from "@/lib/bi"
import { useI18n } from "@/lib/i18n"
import { speakEnglish, TTS_RATE_OPTIONS } from "@/lib/tts"
import { extractErrorMessage } from "@/utils"

const API_BASE = import.meta.env.VITE_API_URL ?? ""

/** 语速选项双语（TTS_RATE_OPTIONS 的 label 目前是单语，渲染时按 value 映射） */
const RATE_LABELS: Record<string, BiString> = {
  "0.5": { zh: "最慢 0.5×", en: "Slowest 0.5×" },
  "0.8": { zh: "慢速 0.8×", en: "Slow 0.8×" },
  "1": { zh: "正常 1.0×", en: "Normal 1.0×" },
}

export default function LimitedListenButton({
  code,
  sessionId,
  itemId,
  text,
  audioUrl,
  replayLimit,
  initialUsed,
}: {
  code: string
  sessionId: string | undefined
  itemId: string
  text: string
  audioUrl?: string | null
  replayLimit: number
  initialUsed: number
}) {
  const { t } = useI18n()
  const [used, setUsed] = useState(initialUsed)
  const [rate, setRate] = useState("1")
  const [loading, setLoading] = useState(false)
  const [playing, setPlaying] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const countingRef = useRef(false)
  const activeRef = useRef(true)
  const unlimited = replayLimit === 0
  const remaining = unlimited ? Infinity : Math.max(0, replayLimit - used)
  const exhausted = !unlimited && remaining <= 0

  useEffect(() => {
    activeRef.current = true
    const audio = audioRef.current
    return () => {
      activeRef.current = false
      audio?.pause()
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel()
      }
    }
  }, [])

  const play = async () => {
    if (exhausted || !sessionId || countingRef.current || playing) return
    countingRef.current = true
    setLoading(true)
    try {
      const counted = await recordListenCount()
      if (!counted || !activeRef.current) return
      if (audioUrl) {
        if (audioRef.current) {
          audioRef.current.playbackRate = Number(rate)
          audioRef.current.currentTime = 0
          if (audioRef.current.error) audioRef.current.load()
          await audioRef.current.play()
          setPlaying(true)
        }
        return
      }
      // TTS 兜底：浏览器合成没有服务端文件，仍走计数
      setPlaying(true)
      const utterance = speakEnglish(text, {
        rate: Number(rate),
        onEnd: () => setPlaying(false),
        onError: playbackError,
      })
      if (!utterance) playbackError()
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError"))
        playbackError()
    } finally {
      countingRef.current = false
      setLoading(false)
    }
  }

  const playbackError = () => {
    if (!activeRef.current) return
    setPlaying(false)
    toast.error(
      t({
        zh: "音频播放失败，请检查网络或设备声音设置",
        en: "Audio playback failed. Check your connection or device audio settings.",
      }),
    )
  }

  const recordListenCount = async (): Promise<boolean> => {
    if (!sessionId) return false
    try {
      const result = await ClassesService.recordListen({
        code,
        requestBody: { session_id: sessionId, item_id: itemId },
      })
      setUsed((prev) => Math.max(prev, result.listen_used))
      return true
    } catch (err) {
      const detail = (err as ApiError).body as { detail?: string } | undefined
      if (
        err instanceof ApiError &&
        err.status === 422 &&
        detail?.detail?.startsWith("可重听次数已用完")
      ) {
        toast.error(t({ zh: "可重听次数已用完", en: "No replays left" }))
        setUsed((prev) => Math.max(prev, replayLimit))
      } else {
        toast.error(extractErrorMessage(err))
      }
      return false
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      {audioUrl && (
        <audio
          ref={audioRef}
          src={audioUrl.startsWith("/") ? `${API_BASE}${audioUrl}` : audioUrl}
          preload="metadata"
          hidden
          onEnded={() => setPlaying(false)}
        >
          <track kind="captions" />
        </audio>
      )}
      <Button
        variant="secondary"
        size="lg"
        onClick={() => void play()}
        disabled={exhausted || loading || playing || !sessionId}
      >
        <Volume2 />
        {loading
          ? t({ zh: "正在加载…", en: "Loading…" })
          : playing
            ? t({ zh: "正在播放…", en: "Playing…" })
            : exhausted
              ? t({ zh: "重听次数已用完", en: "No replays left" })
              : t({ zh: "听示范", en: "Listen" })}
      </Button>
      <span className="text-xs text-muted-foreground">
        {unlimited
          ? t({ zh: "重听不限次", en: "Unlimited replays" })
          : t({
              zh: `还可重听 ${remaining} 次`,
              en: `${remaining} replays left`,
            })}
      </span>
      {!audioUrl && (
        <span className="text-xs text-muted-foreground">
          {t({ zh: "设备合成语音", en: "Device speech" })}
        </span>
      )}
      <label className="sr-only" htmlFor={`listen-rate-${itemId}`}>
        {t({ zh: "示范语速", en: "Speed" })}
      </label>
      <select
        id={`listen-rate-${itemId}`}
        value={rate}
        onChange={(e) => setRate(e.target.value)}
        className="h-9 rounded-lg border border-border bg-card px-2 text-base text-muted-foreground"
      >
        {TTS_RATE_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {t(
              RATE_LABELS[opt.value] ?? {
                zh: String(opt.label),
                en: String(opt.label),
              },
            )}
          </option>
        ))}
      </select>
    </div>
  )
}
