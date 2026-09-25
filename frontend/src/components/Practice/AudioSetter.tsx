import { useMutation } from "@tanstack/react-query"
import { Loader2, Mic, Trash2, Upload, Volume2 } from "lucide-react"
import { useRef } from "react"
import { toast } from "sonner"
import { AdminService } from "@/client"
import { Button } from "@/components/ui/button"

/**
 * 内容配音（PRD §7.2 标准音）：语音合成生成 / 上传现成音频 / 清除。
 * TTS 需配置 ARK_API_KEY；上传通道始终可用。
 */
function AudioSetter({
  hasAudio,
  text,
  onSet,
  stopPropagation = false,
}: {
  hasAudio: boolean
  text: string
  onSet: (audioUrl: string | null) => Promise<unknown>
  /** 外层容器可点击（如卡片头展开）时，阻止按钮点击冒泡 */
  stopPropagation?: boolean
}) {
  const fileRef = useRef<HTMLInputElement>(null)

  const ttsMutation = useMutation({
    mutationFn: () =>
      AdminService.generateStandardAudio({ requestBody: { text } }),
    onSuccess: async (data) => {
      await onSet(data.audio_url ?? null)
      toast.success("标准音已生成")
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(err.body?.detail ?? "生成失败", {
        description: "也可以上传现成的音频文件",
      }),
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      AdminService.uploadStandardAudio({
        formData: { file: file as unknown as string },
      }),
    onSuccess: async (data) => {
      await onSet(data.audio_url ?? null)
      toast.success("音频已上传")
    },
    onError: (err: { body?: { detail?: string } }) =>
      toast.error(err.body?.detail ?? "上传失败"),
  })

  const clear = async () => {
    await onSet(null)
    toast.success("已清除标准音")
  }

  return (
    <div className="flex items-center gap-1">
      {hasAudio && <Volume2 className="size-4 text-primary" />}
      <Button
        variant="ghost"
        size="icon-sm"
        title="语音合成生成标准音（需配置方舟密钥）"
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
        title="上传现成音频"
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
      {hasAudio && (
        <Button
          variant="ghost"
          size="icon-sm"
          title="清除标准音（回退浏览器朗读）"
          onClick={(e) => {
            if (stopPropagation) e.stopPropagation()
            void clear()
          }}
        >
          <Trash2 className="size-3.5 text-destructive" />
        </Button>
      )}
    </div>
  )
}

export default AudioSetter
