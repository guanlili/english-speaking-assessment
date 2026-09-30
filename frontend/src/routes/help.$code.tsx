import { createFileRoute, Link, useParams } from "@tanstack/react-router"
import {
  CheckCircle2,
  Flame,
  Headphones,
  Mic,
  Sparkles,
  Star,
  Volume2,
  XCircle,
} from "lucide-react"
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
import { useI18n } from "@/lib/i18n"
import { EXPLAIN, TERMS } from "@/lib/terms"
import { speakEnglish } from "@/lib/tts"

export const Route = createFileRoute("/help/$code")({
  component: HelpPage,
  head: () => ({
    meta: [{ title: `帮助与设备 / Help & Devices - ${APP_NAME}` }],
  }),
})

function HelpPage() {
  const { t } = useI18n()
  const { code } = useParams({ from: "/help/$code" }) // 课堂码仅用于导航上下文
  const [speakerOk, setSpeakerOk] = useState<boolean | null>(null)
  const [micState, setMicState] = useState<"idle" | "testing" | "ok" | "fail">(
    "idle",
  )
  const [micError, setMicError] = useState<string | null>(null)

  const faqs: Array<[string, string]> = [
    [
      t({
        zh: "说错了，可以再录吗？",
        en: "Can I re-record if I make a mistake?",
      }),
      t({
        zh: "当然可以。停止录音后会自动出反馈，点「再练一次」随时重录，每一次练习都有意义。",
        en: 'Of course. Feedback appears automatically after you stop recording — tap "Practice again" to re-record anytime. Every attempt counts.',
      }),
    ],
    [
      t({
        zh: "为什么分数不是正式成绩？",
        en: "Why isn't the score an official result?",
      }),
      t({
        zh: "跟读参考分、模拟分和词汇分析分别来自不同来源，帮助你发现下一步怎么练，不是官方考试成绩。",
        en: "Reference scores, mock scores and vocabulary analysis come from different sources. They help you see what to practice next — they are not official exam results.",
      }),
    ],
    [
      t({ zh: "我的录音保存在哪里？", en: "Where are my recordings stored?" }),
      t({
        zh: "录音上传到课堂服务器，只有你自己和本课授权老师可以回听，用于学习反馈，不做其他用途。",
        en: "Recordings are uploaded to the classroom server. Only you and your classroom's authorized teacher can play them back, for learning feedback only.",
      }),
    ],
    [
      t({
        zh: "练到一半想休息？",
        en: "Want a break in the middle of practice?",
      }),
      t({
        zh: "已完成的题目会自动保留，回来继续就行。录音还没提交时会提醒你确认后再离开。",
        en: "Completed items are saved automatically — just come back and continue. If a recording hasn't been submitted yet, you'll be asked to confirm before leaving.",
      }),
    ],
  ]

  const testSpeaker = () => {
    setSpeakerOk(null)
    const utterance = speakEnglish(
      "Hello! Can you hear me? If you can hear this, your speaker works.",
      { onEnd: () => setSpeakerOk(true), onError: () => setSpeakerOk(false) },
    )
    if (utterance === null) {
      setSpeakerOk(false)
    }
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
          ? t({
              zh: "麦克风权限未开启。点击浏览器地址栏的锁/麦克风图标，允许后重试。",
              en: "Microphone permission is off. Click the lock/microphone icon in the browser address bar, allow it, then retry.",
            })
          : t({
              zh: "没有找到可用麦克风，请检查耳机连接。",
              en: "No microphone found — please check your headset connection.",
            }),
      )
    }
  }

  return (
    <StudentShell active="help">
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {t({
              zh: "准备好设备，安心开口。",
              en: "Get your device ready and speak with confidence.",
            })}
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            {t({
              zh: "第一次练习也没关系，我们一步一步来。",
              en: "First time practicing? No problem — let's take it step by step.",
            })}
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t({
                zh: "开始前的小检查",
                en: "A quick check before you start",
              })}
            </CardTitle>
            <CardDescription>
              {t({
                zh: "三项都通过，练习就不会被打断",
                en: "Pass all three and your practice won't be interrupted",
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-2.5 text-sm">
              <Headphones className="size-4 shrink-0 text-primary" />
              {t({
                zh: "戴上耳机，减少环境噪声和示范音回声",
                en: "Wear your headset to reduce background noise and echo from the model audio",
              })}
            </div>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <div className="flex items-center gap-2.5">
                <Volume2 className="size-4 shrink-0 text-primary" />
                <Button variant="secondary" size="sm" onClick={testSpeaker}>
                  {t({ zh: "测试扬声器", en: "Test speaker" })}
                </Button>
              </div>
              {speakerOk === true && (
                <span className="flex items-center gap-1 text-xs text-primary">
                  <CheckCircle2 className="size-3.5" />{" "}
                  {t({ zh: "能听到声音", en: "Sound is audible" })}
                </span>
              )}
              {speakerOk === false && (
                <span className="flex items-center gap-1 text-xs text-destructive">
                  <XCircle className="size-3.5" />
                  {t({
                    zh: "没有声音？检查设备音量与浏览器静音设置",
                    en: "No sound? Check device volume and browser mute settings",
                  })}
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
                  {micState === "testing"
                    ? t({ zh: "测试中…", en: "Testing…" })
                    : t({ zh: "测试麦克风", en: "Test microphone" })}
                </Button>
              </div>
              {micState === "ok" && (
                <span className="flex items-center gap-1 text-xs text-primary">
                  <CheckCircle2 className="size-3.5" />{" "}
                  {t({ zh: "麦克风工作正常", en: "Microphone works" })}
                </span>
              )}
              {micState === "fail" && (
                <span className="text-xs text-destructive">
                  {micError ??
                    t({ zh: "麦克风不可用", en: "Microphone unavailable" })}
                </span>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t({ zh: "常见问题", en: "FAQ" })}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-0">
            {faqs.map(([q, a]) => (
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
            <CardTitle className="text-base">
              {t({
                zh: "分数与激励怎么算",
                en: "How scores and rewards work",
              })}
            </CardTitle>
            <CardDescription>
              {t({
                zh: "练习中会看到这些数字，它们的含义都在这里",
                en: "You'll see these numbers while practicing — here's what they mean",
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-start gap-2.5">
              <Sparkles className="mt-0.5 size-4 shrink-0 text-primary" />
              <p className="leading-relaxed">
                <span className="font-semibold">
                  {t(TERMS.score)}
                  {t({ zh: "：", en: ": " })}
                </span>
                {t(EXPLAIN.score)}
              </p>
            </div>
            <div className="flex items-start gap-2.5">
              <Star className="mt-0.5 size-4 shrink-0 text-yellow-500" />
              <p className="leading-relaxed">
                <span className="font-semibold">
                  {t({ zh: "星级", en: "Stars" })}
                  {t({ zh: "：", en: ": " })}
                </span>
                {t(EXPLAIN.stars)}
              </p>
            </div>
            <div className="flex items-start gap-2.5">
              <Sparkles className="mt-0.5 size-4 shrink-0 text-primary" />
              <p className="leading-relaxed">
                <span className="font-semibold">
                  XP{t({ zh: "：", en: ": " })}
                </span>
                {t(EXPLAIN.xp)}
              </p>
            </div>
            <div className="flex items-start gap-2.5">
              <Flame className="mt-0.5 size-4 shrink-0 text-orange-500" />
              <p className="leading-relaxed">
                <span className="font-semibold">
                  {t({ zh: "连胜", en: "Streak" })}
                  {t({ zh: "：", en: ": " })}
                </span>
                {t(EXPLAIN.streak)}
              </p>
            </div>
            <div className="flex items-start gap-2.5">
              <Star className="mt-0.5 size-4 shrink-0 text-yellow-500" />
              <p className="leading-relaxed">
                <span className="font-semibold">
                  {t({ zh: "徽章", en: "Badges" })}
                  {t({ zh: "：", en: ": " })}
                </span>
                {t(EXPLAIN.badges)}
              </p>
            </div>
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "自己的累计数据在",
                en: "Find your own totals in",
              })}{" "}
              <Link
                to="/me/$code"
                params={{ code }}
                className="font-medium text-primary hover:underline"
              >
                {t(TERMS.growthPage)}
              </Link>
              .
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t({
                zh: "放心开口的小约定",
                en: "Our little agreement for safe speaking",
              })}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5 text-sm">
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              {t({
                zh: "显示名 + 区分码识别身份，不需要注册账号。",
                en: "Your display name plus a distinct code identifies you — no account registration needed.",
              })}
            </p>
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              {t({
                zh: "成绩仅供学习参考；老师关注的是你的变化，不是一次分数。",
                en: "Scores are for learning only; your teacher cares about your progress, not a single score.",
              })}
            </p>
            <p className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              {t({
                zh: "没有班级排名，只和自己比。说错了没关系，再试一次就好。",
                en: "No class rankings — compare only with yourself. Mistakes are fine; just try again.",
              })}
            </p>
          </CardContent>
        </Card>
      </div>
    </StudentShell>
  )
}
