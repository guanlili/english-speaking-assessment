import { type RefObject, useEffect, useRef, useState } from "react"
import { ClassesService, type TodayPlan } from "@/client"
import type { useRecorder } from "@/hooks/useRecorder"
import { EXAM_AUDIO_UNLOCK_URL } from "@/lib/exam-audio"
import { checkExamAudio, ExamAudioCheckError } from "@/lib/exam-audio-check"
import { useI18n } from "@/lib/i18n"

export function useExamAudioDevice({
  code,
  plan,
  recorderRef,
  refetch,
  setError,
}: {
  code: string
  plan: TodayPlan
  recorderRef: RefObject<ReturnType<typeof useRecorder>>
  refetch: () => Promise<unknown>
  setError: (message: string | null) => void
}) {
  const { t } = useI18n()
  const exam = plan.exam
  const phase = exam?.phase
  const item = plan.items[exam?.current_item_index ?? 0]
  const [deviceIssue, setDeviceIssue] = useState<"device" | "audio" | null>(
    null,
  )
  const [armed, setArmed] = useState(false)
  const [enabling, setEnabling] = useState(false)
  const enablingRef = useRef(false)
  const audioCheck = useRef<AbortController | null>(null)
  const context = useRef<AudioContext | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)
  function playerCleanup() {
    audio.current?.pause()
    window.speechSynthesis?.cancel()
  }
  async function enable() {
    if (enablingRef.current) return
    enablingRef.current = true
    setEnabling(true)
    setError(null)
    const check = new AbortController()
    audioCheck.current = check
    let stage: "audio" | "device" | "sync" = "audio"
    try {
      context.current ??= new AudioContext()
      const player = audio.current ?? new Audio(EXAM_AUDIO_UNLOCK_URL)
      audio.current = player
      player.onended = null
      player.onerror = null
      player.src = EXAM_AUDIO_UNLOCK_URL
      // Both calls happen synchronously within the student's device-check click.
      await Promise.all([
        context.current.resume(),
        player.play(),
        checkExamAudio(
          exam?.started
            ? phase === "audio" && item
              ? [item]
              : []
            : plan.items,
          check.signal,
        ),
      ])
      player.pause()
      stage = "device"
      await recorderRef.current.prepare()
      stage = "sync"
      if (check.signal.aborted) return
      if (!exam?.started)
        await ClassesService.startExam({
          code,
          requestBody: { session_id: plan.session_id },
        })
      await refetch()
      setArmed(true)
      setDeviceIssue(null)
    } catch (err) {
      if (check.signal.aborted) return
      setDeviceIssue(stage === "sync" ? null : stage)
      check.abort()
      playerCleanup()
      setError(
        t(
          err instanceof ExamAudioCheckError
            ? {
                zh: "考试音频检查失败，尚未开始新考试。请检查网络后重试；若仍失败，请联系老师检查题目音频。已开始的考试计时继续。",
                en: "Exam audio check failed; no new exam was started. Check your connection and retry, or ask your teacher to check the audio. An exam already started keeps counting down.",
              }
            : {
                zh: "请允许麦克风和声音播放，再重试。",
                en: "Allow microphone and audio playback, then retry.",
              },
        ),
      )
    } finally {
      enablingRef.current = false
      setEnabling(false)
    }
  }
  function beep(): Promise<void> {
    const ctx = context.current
    if (!ctx) return Promise.resolve()
    const oscillator = ctx.createOscillator()
    const gain = ctx.createGain()
    oscillator.connect(gain)
    gain.connect(ctx.destination)
    oscillator.frequency.value = 880
    gain.gain.value = 0.12
    oscillator.start()
    oscillator.stop(ctx.currentTime + 0.15)
    return new Promise((resolve) => {
      oscillator.onended = () => {
        oscillator.disconnect()
        gain.disconnect()
        resolve()
      }
    })
  }
  const beepRef = useRef(beep)
  beepRef.current = beep

  useEffect(
    () => () => {
      audioCheck.current?.abort()
      audio.current?.pause()
      window.speechSynthesis?.cancel()
      void context.current?.close()
    },
    [],
  )
  return { deviceIssue, armed, setArmed, enabling, enable, audio, beepRef }
}
