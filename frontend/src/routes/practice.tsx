import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { BookOpen, Mic, Sparkles, Square } from "lucide-react"
import { useEffect } from "react"
import { toast } from "sonner"
import { PracticeService } from "@/client"
import FeedbackCard from "@/components/Practice/FeedbackCard"
import SpeakButton from "@/components/Practice/SpeakButton"
import { Card, CardContent } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { APP_NAME } from "@/config"
import { useAttemptSubmit } from "@/hooks/useAttemptSubmit"
import { MAX_RECORD_SECONDS, useRecorder } from "@/hooks/useRecorder"

export const Route = createFileRoute("/practice")({
  component: PracticePage,
  head: () => ({
    meta: [{ title: `篇章跟读 - ${APP_NAME}` }],
  }),
})

function formatSeconds(seconds: number): string {
  const whole = Math.floor(seconds)
  return `${String(Math.floor(whole / 60)).padStart(1, "0")}:${String(whole % 60).padStart(2, "0")}`
}

function PracticePage() {
  const passageQuery = useQuery({
    retry: 1,
    retryDelay: 500,
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
        正在加载篇章…
      </div>
    )
  }

  if (passageQuery.isError || !passageQuery.data) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        篇章加载失败，请刷新重试。
      </div>
    )
  }

  const passage = passageQuery.data

  return (
    <div className="page-enter min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-5 md:p-8">
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            篇章跟读
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              {passage.topic} · {passage.cefr_band} ·{" "}
              {formatSeconds(passage.suggested_seconds ?? 45)}
            </span>
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            先完整听一遍，再按照自己的节奏朗读整篇。
          </p>
        </div>

        <Card>
          <CardContent className="space-y-5 pt-6">
            <span className="text-xs font-semibold tracking-wide text-primary">
              <BookOpen className="mr-1 inline size-3.5" />
              READ ALOUD · 让文字有声音
            </span>

            <p className="prompt-display">
              {passage.translation ?? "先听示范，再戴上耳机朗读整篇。"}
            </p>
            <p className="text-sm leading-relaxed">{passage.text}</p>

            <SpeakButton text={passage.text} audioUrl={passage.audio_url} />

            <Separator />

            {/* 录音区（SpeakUp：大圆钮 + 波形） */}
            <div className="flex flex-col items-center gap-1 border-t pt-5 text-center">
              {recorder.status === "recording" ? (
                <>
                  <div
                    className="flex h-8 items-center justify-center gap-1"
                    aria-hidden
                  >
                    {Array.from({ length: 25 }).map((_, i) => (
                      <i
                        key={i}
                        className="wave-bar block w-[3px] rounded bg-primary"
                        style={{
                          height: `${[7, 20, 29, 13, 18, 24, 10, 16, 28, 12][i % 10]}px`,
                          animationDelay: `${(i % 5) * -0.2}s`,
                        }}
                      />
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={recorder.stop}
                    aria-label="结束录音"
                    className="record-pulse mt-3 grid size-[72px] place-items-center rounded-full bg-destructive text-white shadow-[0_0_0_7px_var(--accent)] transition hover:scale-105"
                  >
                    <Square className="size-7" />
                  </button>
                  <p className="mt-4 text-sm">
                    <span className="font-mono tabular-nums">
                      {formatSeconds(recorder.elapsed)}
                    </span>{" "}
                    · 读完后点一下结束
                  </p>
                  <p className="text-xs text-muted-foreground">
                    最长 {formatSeconds(MAX_RECORD_SECONDS)} ·
                    不用着急，按自己的节奏说
                  </p>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => recorder.start()}
                    disabled={submitting}
                    aria-label="开始录音"
                    className="mt-1 grid size-[72px] place-items-center rounded-full bg-primary text-white shadow-[0_0_0_7px_var(--secondary)] transition hover:scale-105 disabled:opacity-50"
                  >
                    <Mic className="size-7" />
                  </button>
                  <p className="mt-4 text-sm">
                    {recorder.status === "ready" && submitting
                      ? "已提交，正在出反馈…"
                      : recorder.status === "ready"
                        ? "这一次开口，已记录"
                        : "准备好了，就点一下麦克风"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    需要麦克风权限 · 每一次练习都有意义
                  </p>
                </>
              )}
              {recorder.error && (
                <p className="mt-1 text-sm text-destructive">
                  {recorder.error}
                </p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* 表达支架 */}
        <Card className="border-secondary bg-secondary/60">
          <CardContent className="space-y-2 py-4">
            <p className="flex items-center gap-1.5 text-sm font-semibold">
              <Sparkles className="size-4 text-primary" /> 一个小小的提示
            </p>
            <p className="text-sm text-muted-foreground">
              整篇朗读时跟着意群停顿，不追求速度。
            </p>
            <p className="font-serif text-xl">Listen. Pause. Speak.</p>
            <p className="text-xs text-muted-foreground">
              听一遍 · 想一想 · 大胆说
            </p>
          </CardContent>
        </Card>

        {attempt !== undefined && (
          <FeedbackCard attempt={attempt} onRepractice={repractice} />
        )}

        <p className="pb-6 text-center text-xs text-muted-foreground">
          篇章跟读不计入课堂任务 · 分数是参考反馈，不是考试成绩。
        </p>
      </div>
    </div>
  )
}
