import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Circle, Mic, Square } from "lucide-react"
import { useEffect } from "react"
import { toast } from "sonner"
import { PracticeService } from "@/client"
import FeedbackCard from "@/components/Practice/FeedbackCard"
import SpeakButton from "@/components/Practice/SpeakButton"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { APP_NAME } from "@/config"
import { useAttemptSubmit } from "@/hooks/useAttemptSubmit"
import { MAX_RECORD_SECONDS, useRecorder } from "@/hooks/useRecorder"

export const Route = createFileRoute("/practice")({
  component: PracticePage,
  head: () => ({
    meta: [{ title: `口语练习 - ${APP_NAME}` }],
  }),
})

function formatSeconds(seconds: number): string {
  const whole = Math.floor(seconds)
  return `${String(Math.floor(whole / 60)).padStart(1, "0")}:${String(whole % 60).padStart(2, "0")}`
}

function PracticePage() {
  const passageQuery = useQuery({
    queryKey: ["practice", "passage"],
    queryFn: () => PracticeService.readActivePassage(),
  })

  const { submit, submitting, attempt, submitError } = useAttemptSubmit({
    itemType: "passage",
    itemId: passageQuery.data?.id ?? "",
  })

  // PRD US-02：停止后自动上传（onstop 里恰好触发一次；过短的已被 hook 拦下）
  const recorder = useRecorder({
    onComplete: (rec) => submit({ blob: rec.blob, duration: rec.duration }),
  })

  useEffect(() => {
    if (submitError) {
      toast.error("上传失败", { description: "请检查网络后再录一次" })
    }
  }, [submitError])

  const repractice = () => recorder.reset()

  if (passageQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        正在加载今天的练习…
      </div>
    )
  }

  if (passageQuery.isError || !passageQuery.data) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        练习内容加载失败，请刷新重试。
      </div>
    )
  }

  const passage = passageQuery.data

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">口语练习</CardTitle>
            <CardDescription>
              今天的主题：{passage.topic} · {passage.cefr_band} · 建议时长{" "}
              {formatSeconds(passage.suggested_seconds ?? 45)}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <SpeakButton text={passage.text} audioUrl={passage.audio_url} />
            <p className="text-lg leading-relaxed">{passage.text}</p>

            <Separator />

            <div className="flex flex-col gap-2">
              {recorder.status === "recording" ? (
                <Button
                  variant="destructive"
                  size="lg"
                  onClick={recorder.stop}
                  className="w-fit"
                >
                  <Square />
                  停止（{formatSeconds(recorder.elapsed)} /{" "}
                  {formatSeconds(MAX_RECORD_SECONDS)}）
                </Button>
              ) : (
                <Button
                  size="lg"
                  onClick={() => recorder.start()}
                  disabled={submitting}
                  className="w-fit"
                >
                  <Mic />
                  开始录音
                </Button>
              )}

              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                {recorder.status === "recording" && (
                  <>
                    <Circle className="size-2 animate-pulse fill-destructive text-destructive" />
                    正在录音 {recorder.elapsed.toFixed(0)}s，读完点「停止」
                  </>
                )}
                {recorder.status === "idle" && <>录音状态：未录</>}
                {recorder.status === "ready" && submitting && (
                  <>已提交，正在出反馈…</>
                )}
                {recorder.status === "ready" && !submitting && <>录音完成</>}
              </p>

              {recorder.error && (
                <p className="text-sm text-destructive">{recorder.error}</p>
              )}
            </div>
          </CardContent>
        </Card>

        {attempt !== undefined && (
          <FeedbackCard attempt={attempt} onRepractice={repractice} />
        )}

        <p className="pb-6 text-center text-xs text-muted-foreground">
          先听一遍，戴上耳机朗读录音；反馈出来后可以立刻再练一次。
        </p>
      </div>
    </div>
  )
}
