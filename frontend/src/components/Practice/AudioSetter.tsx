import { useMutation } from "@tanstack/react-query"
import { Loader2, Mic, Square, Upload, Volume2, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { AdminService } from "@/client"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"

const API_BASE = import.meta.env.VITE_API_URL ?? ""

function AudioPreview({
  audioUrl,
  stopPropagation,
}: {
  audioUrl: string
  stopPropagation: boolean
}) {
  const { t } = useI18n()
  const audioRef = useRef<HTMLAudioElement>(null)
  const failedRef = useRef(false)
  const [playing, setPlaying] = useState(false)
  const src = audioUrl.startsWith("/") ? `${API_BASE}${audioUrl}` : audioUrl

  useEffect(() => {
    const audio = audioRef.current
    return () => audio?.pause()
  }, [])

  const reportError = () => {
    setPlaying(false)
    if (failedRef.current) return
    failedRef.current = true
    toast.error(
      t({
        zh: "音频播放失败，请重试或重新生成标准音",
        en: "Audio playback failed. Retry or regenerate the audio.",
      }),
    )
  }
  const label = playing
    ? t({ zh: "停止试听", en: "Stop preview" })
    : t({ zh: "试听标准音", en: "Preview audio" })

  return (
    <>
      <audio
        ref={audioRef}
        src={src}
        preload="none"
        onEnded={() => setPlaying(false)}
        onPause={() => setPlaying(false)}
        onError={reportError}
      >
        <track kind="captions" />
      </audio>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        title={label}
        aria-label={label}
        aria-pressed={playing}
        onClick={(e) => {
          if (stopPropagation) e.stopPropagation()
          const audio = audioRef.current
          if (!audio) return
          if (playing) {
            audio.pause()
            audio.currentTime = 0
            setPlaying(false)
            return
          }
          failedRef.current = false
          // Reload on retry so a transient file/network error can recover.
          if (audio.error) audio.load()
          audio.currentTime = 0
          setPlaying(true)
          void audio.play().catch((err: unknown) => {
            // Stop, replacement and unmount intentionally interrupt playback.
            if (err instanceof DOMException && err.name === "AbortError") return
            reportError()
          })
        }}
      >
        {playing ? (
          <Square className="size-4 text-primary" />
        ) : (
          <Volume2 className="size-4 text-primary" />
        )}
      </Button>
    </>
  )
}

/**
 * 内容配音（PRD §7.2 标准音）：语音合成生成 / 上传现成音频 / 清除。
 * TTS 需配置 ARK_API_KEY；上传通道始终可用。
 */
function AudioSetter({
  audioUrl,
  text,
  onSet,
  stopPropagation = false,
}: {
  audioUrl?: string | null
  text: string
  onSet: (audioUrl: string | null) => Promise<unknown>
  /** 外层容器可点击（如卡片头展开）时，阻止按钮点击冒泡 */
  stopPropagation?: boolean
}) {
  const { t } = useI18n()
  const fileRef = useRef<HTMLInputElement>(null)

  const ttsMutation = useMutation({
    mutationFn: () =>
      AdminService.generateStandardAudio({ requestBody: { text } }),
    onSuccess: async (data) => {
      await onSet(data.audio_url ?? null)
      toast.success(t({ zh: "标准音已生成", en: "Audio generated" }))
    },
    onError: (err: unknown) =>
      toast.error(extractErrorMessage(err), {
        description: t({
          zh: "也可以上传现成的音频文件",
          en: "You can also upload an audio file.",
        }),
      }),
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      AdminService.uploadStandardAudio({
        formData: { file: file as unknown as string },
      }),
    onSuccess: async (data) => {
      await onSet(data.audio_url ?? null)
      toast.success(t({ zh: "音频已上传", en: "Audio uploaded" }))
    },
    onError: (err: unknown) => toast.error(extractErrorMessage(err)),
  })

  const clear = async () => {
    try {
      await onSet(null)
      toast.success(t({ zh: "已清除标准音", en: "Audio cleared" }))
    } catch (err) {
      toast.error(extractErrorMessage(err))
    }
  }

  return (
    <div className="flex items-center gap-1">
      {audioUrl && (
        <AudioPreview
          key={audioUrl}
          audioUrl={audioUrl}
          stopPropagation={stopPropagation}
        />
      )}
      <Button
        variant="ghost"
        size="icon-sm"
        type="button"
        title={t({
          zh: "语音合成生成标准音（需配置方舟密钥）",
          en: "Generate audio with AI (requires an Ark API key)",
        })}
        aria-label={t({
          zh: "语音合成生成标准音（需配置方舟密钥）",
          en: "Generate audio with AI (requires an Ark API key)",
        })}
        onClick={(e) => {
          if (stopPropagation) e.stopPropagation()
          ttsMutation.mutate()
        }}
        disabled={ttsMutation.isPending || !text}
      >
        {ttsMutation.isPending ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <Mic className="size-3.5" />
        )}
      </Button>
      <input
        ref={fileRef}
        type="file"
        accept=".mp3,.wav,.m4a,.ogg,.webm,audio/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) uploadMutation.mutate(file)
          if (fileRef.current) fileRef.current.value = ""
        }}
      />
      <Button
        variant="ghost"
        size="icon-sm"
        type="button"
        title={t({ zh: "上传现成音频", en: "Upload audio" })}
        aria-label={t({ zh: "上传现成音频", en: "Upload audio" })}
        onClick={(e) => {
          if (stopPropagation) e.stopPropagation()
          fileRef.current?.click()
        }}
        disabled={uploadMutation.isPending}
      >
        {uploadMutation.isPending ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <Upload className="size-3.5" />
        )}
      </Button>
      {audioUrl && (
        <Button
          variant="ghost"
          size="icon-sm"
          type="button"
          title={t({
            zh: "清除标准音（回退浏览器朗读）",
            en: "Clear audio (use device speech instead)",
          })}
          aria-label={t({
            zh: "清除标准音（回退浏览器朗读）",
            en: "Clear audio (use device speech instead)",
          })}
          onClick={(e) => {
            if (stopPropagation) e.stopPropagation()
            void clear()
          }}
        >
          <X className="size-3.5 text-muted-foreground" />
        </Button>
      )}
    </div>
  )
}

export default AudioSetter
