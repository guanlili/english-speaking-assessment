import { Volume2 } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"

/**
 * 标准音播放。audioUrl 存在时用音频文件（离线生成的 mp3），
 * 否则回退到浏览器 speechSynthesis（PRD §7.2：2 天演示允许）。
 */
const API_BASE = import.meta.env.VITE_API_URL ?? ""

function SpeakButton({
  text,
  audioUrl,
}: {
  text: string
  audioUrl?: string | null
}) {
  const [playing, setPlaying] = useState(false)

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
    utterance.rate = 0.95
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
    <Button variant="outline" size="lg" onClick={speak} disabled={playing}>
      <Volume2 />
      {playing ? "正在播放…" : "听标准读音"}
    </Button>
  )
}

export default SpeakButton
