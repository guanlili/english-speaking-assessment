import { createFileRoute, useParams } from "@tanstack/react-router"
import { CheckCircle2, Headphones, Mic, Volume2, XCircle } from "lucide-react"
import { useState } from "react"
import StudentShell from "@/components/Practice/StudentShell"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { APP_NAME } from "@/config"

export const Route = createFileRoute("/help/$code")({
  component: HelpPage,
  head: () => ({ meta: [{ title: `帮助与设备 - ${APP_NAME}` }] }),
})

const FAQS: Array<[string, string]> = [
  [
    "说错了，可以再录吗？",
    "当然可以。停止录音后会自动出反馈，点「再练一次」随时重录，每一次练习都有意义。",
  ],
  [
    "为什么分数不是正式成绩？",
    "跟读分、模型模拟分、词汇档位分别来自不同来源，都标了「参考」，帮助你发现下一步怎么练，不是官方考试成绩。",
  ],
  [
    "我的录音保存在哪里？",
    "录音上传到课堂服务器，只有你的老师可以回听，用于学习反馈，不做其他用途。",
  ],
  [
    "练到一半想休息？",
    "已完成的题目会自动保留，回来继续就行。录音还没提交时会提醒你确认后再离开。",
  ],
]

function HelpPage() {
  useParams({ from: "/help/$code" }) // 课堂码仅用于导航上下文
  const [speakerOk, setSpeakerOk] = useState<boolean | null>(null)
  const [micState, setMicState] = useState<"idle" | "testing" | "ok" | "fail">(
    "idle",
  )
  const [micError, setMicError] = useState<string | null>(null)

  const testSpeaker = () => {
    const synth = window.speechSynthesis
    if (!synth) {
      setSpeakerOk(false)
      return
    }
    synth.cancel()
    const utterance = new SpeechSynthesisUtterance(
      "Hello! Can you hear me? If you can hear this, your speaker works.",
    )
    utterance.lang = "en-US"
    utterance.onend = () => setSpeakerOk(true)
    utterance.onerror = () => setSpeakerOk(false)
    setSpeakerOk(null)
    synth.speak(utterance)
  }

  const testMic = async () => {
    setMicState("testing")
    setMicError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach((t) => {
        t.stop()
      })
      setMicState("ok")
    } catch (error) {
      setMicState("fail")
      const name = error instanceof DOMException ? error.name : ""
      setMicError(
        name === "NotAllowedError"
          ? "麦克风权限未开启。点击浏览器地址栏的锁/麦克风图标，允许后重试。"
          : "没有找到可用麦克风，请检查耳机连接。",
      )
    }
  }

  return (
    <StudentShell active="help">
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            准备好设备，安心开口。
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            第一次练习也没关系，我们一步一步来。
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">开始前的小检查</CardTitle>
            <CardDescription>三项都通过，练习就不会被打断</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-2.5 text-sm">
              <Headphones className="size-4 shrink-0 text-primary" />
              戴上耳机，减少环境噪声和示范音回声
            </div>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <div className="flex items-center gap-2.5">
                <Volume2 className="size-4 shrink-0 text-primary" />
                <Button variant="secondary" size="sm" onClick={testSpeaker}>
                  测试扬声器
                </Button>
              </div>
              {speakerOk === true && (
                <span className="flex items-center gap-1 text-xs text-primary">
                  <CheckCircle2 className="size-3.5" /> 能听到声音
                </span>
              )}
              {speakerOk === false && (
                <span className="flex items-center gap-1 text-xs text-destructive">
                  <XCircle className="size-3.5" />
                  没有声音？检查设备音量与浏览器静音设置
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <div className="flex items-center gap-2.5">
                <Mic className="size-4 shrink-0 text-primary" />
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void testMic()}
                  disabled={micState === "testing"}
                >
                  {micState === "testing" ? "测试中…" : "测试麦克风"}
                </Button>
              </div>
              {micState === "ok" && (
                <span className="flex items-center gap-1 text-xs text-primary">
                  <CheckCircle2 className="size-3.5" /> 麦克风工作正常
                </span>
              )}
              {micState === "fail" && (
                <span className="text-xs text-destructive">
                  {micError ?? "麦克风不可用"}
                </span>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">常见问题</CardTitle>
          </CardHeader>
          <CardContent className="space-y-0">
            {FAQS.map(([q, a]) => (
              <details
                key={q}
                className="border-b border-border py-4 last:border-0"
              >
                <summary className="cursor-pointer text-sm font-semibold">
                  {q}
                </summary>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  {a}
                </p>
              </details>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">放心开口的小约定</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5 text-sm">
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              显示名 + 区分码识别身份，不需要注册账号。
            </p>
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              成绩仅供学习参考；老师关注的是你的变化，不是一次分数。
            </p>
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              没有班级排名，只和自己比。说错了没关系，再试一次就好。
            </p>
          </CardContent>
        </Card>
      </div>
    </StudentShell>
  )
}
