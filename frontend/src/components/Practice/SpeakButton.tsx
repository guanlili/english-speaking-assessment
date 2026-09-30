import { Volume2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import type { BiString } from "@/lib/bi"
import { useI18n } from "@/lib/i18n"
import { speakEnglish, TTS_RATE_OPTIONS } from "@/lib/tts"

const API_BASE = import.meta.env.VITE_API_URL ?? ""

/** 语速选项双语（TTS_RATE_OPTIONS 的 label 目前是单语，渲染时按 value 映射） */
const RATE_LABELS: Record<string, BiString> = {
  "0.5": { zh: "最慢 0.5×", en: "Slowest 0.5×" },
  "0.8": { zh: "慢速 0.8×", en: "Slow 0.8×" },
  "1": { zh: "正常 1.0×", en: "Normal 1.0×" },
}

/**
 * 标准音播放。audioUrl 存在时用音频文件；否则浏览器 speechSynthesis
 * 并提供语速选择（PRD §7.2：2 天演示允许）。
 */
function SpeakButton({
  text,
  audioUrl,
}: {
  text: string
  audioUrl?: string | null
}) {
  const { t } = useI18n()
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState("1")
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null)

  useEffect(() => {
    return () => {
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel()
      }
      utteranceRef.current = null
    }
  }, [])

  if (audioUrl) {
    const src = audioUrl.startsWith("/") ? `${API_BASE}${audioUrl}` : audioUrl
    return (
      <audio controls src={src} className="w-full">
        <track kind="captions" />
      </audio>
    )
  }

  const speak = () => {
    const utterance = speakEnglish(text, {
      rate: Number(rate),
      onEnd: () => {
        setPlaying(false)
        utteranceRef.current = null
      },
      onError: () => {
        setPlaying(false)
        utteranceRef.current = null
      },
    })
    if (utterance) {
      utteranceRef.current = utterance
      setPlaying(true)
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <Button variant="secondary" size="lg" onClick={speak} disabled={playing}>
        <Volume2 />
        {playing
          ? t({ zh: "正在播放…", en: "Playing…" })
          : t({ zh: "听示范", en: "Listen" })}
      </Button>
      <div className="flex items-center gap-2">
        <label className="sr-only" htmlFor="speech-rate">
          {t({ zh: "示范语速", en: "Speed" })}
        </label>
        <select
          id="speech-rate"
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
    </div>
  )
}

export default SpeakButton
