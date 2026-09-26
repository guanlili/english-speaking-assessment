import { Volume2 } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"

const API_BASE = import.meta.env.VITE_API_URL ?? ""

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
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState("1")

  if (audioUrl) {
    const src = audioUrl.startsWith("/") ? `${API_BASE}${audioUrl}` : audioUrl
    return (
      <audio controls src={src} className="w-full">
        <track kind="captions" />
      </audio>
    )
  }

  const speak = () => {
    const synth = window.speechSynthesis
    if (!synth) return
    synth.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = "en-US"
    utterance.rate = Number(rate)
    const voice = synth.getVoices().find((v) => v.lang.startsWith("en"))
    if (voice) {
      utterance.voice = voice
    }
    utterance.onend = () => setPlaying(false)
    utterance.onerror = () => setPlaying(false)
    setPlaying(true)
    synth.speak(utterance)
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <Button variant="secondary" size="lg" onClick={speak} disabled={playing}>
        <Volume2 />
        {playing ? "正在播放…" : "听示范"}
      </Button>
      <div className="flex items-center gap-2">
        <label className="sr-only" htmlFor="speech-rate">
          示范语速
        </label>
        <select
          id="speech-rate"
          value={rate}
          onChange={(e) => setRate(e.target.value)}
          className="h-9 rounded-lg border border-border bg-card px-2 text-xs text-muted-foreground"
        >
          <option value="0.8">慢速 0.8×</option>
          <option value="1">正常 1.0×</option>
        </select>
      </div>
    </div>
  )
}

export default SpeakButton
