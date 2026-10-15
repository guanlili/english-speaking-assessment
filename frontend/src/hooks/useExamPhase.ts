import { type RefObject, useEffect, useRef } from "react"
import type { PlanItem, TodayPlan } from "@/client"
import type { useRecorder } from "@/hooks/useRecorder"
import { useI18n } from "@/lib/i18n"
import type { RecordingDraftInput } from "@/lib/recording-drafts"
import { speakEnglish } from "@/lib/tts"
import { randomId } from "@/utils"

type ExamEvent = {
  session_id: string
  item_id: string
  event: "audio-ended" | "next"
}

export function useExamPhase({
  armed,
  draftsReady,
  latest,
  phase,
  stageKey,
  pendingDraft,
  owner,
  code,
  sessionId,
  accepted,
  recordingStarted,
  target,
  recorderRef,
  audio,
  beepRef,
  eventRef,
  setArmed,
  setError,
}: {
  armed: boolean
  draftsReady: boolean
  latest: RefObject<{
    plan: TodayPlan
    item: PlanItem | undefined
    syncedAt: number
  }>
  phase: string | null | undefined
  stageKey: string
  pendingDraft: RecordingDraftInput | null
  owner: string | null
  code: string
  sessionId: string
  accepted: RefObject<Set<string>>
  recordingStarted: RefObject<Set<string>>
  target: RefObject<RecordingDraftInput | null>
  recorderRef: RefObject<ReturnType<typeof useRecorder>>
  audio: RefObject<HTMLAudioElement | null>
  beepRef: RefObject<() => Promise<void>>
  eventRef: RefObject<(event: ExamEvent) => void>
  setArmed: (armed: boolean) => void
  setError: (message: string | null) => void
}) {
  const { t } = useI18n()
  // effect 内只有 failed 回调用到 t：语言切换会换 t 引用，进了依赖数组
  // 会把正在播放的听力题 cleanup 掉并从头重播（服务端计时照走，音频与
  // 题窗错位）。文案经 ref 解耦，依赖数组不含 t
  const audioFailText = () =>
    t({
      zh: "音频未播放完成，请启用声音后继续。",
      en: "Audio did not finish. Enable sound to continue.",
    })
  const audioFailTextRef = useRef(audioFailText)
  audioFailTextRef.current = audioFailText

  useEffect(() => {
    if (!armed || !draftsReady) return
    const current = latest.current
    const currentItem = current.item
    const currentExam = current.plan.exam
    if (!currentItem || !currentExam || currentExam.ended) return
    let cancelled = false
    if (phase === "audio") {
      const ended = () => {
        if (!cancelled)
          eventRef.current({
            session_id: current.plan.session_id,
            item_id: currentItem.id,
            event: "audio-ended",
          })
      }
      const failed = () => {
        if (!cancelled) {
          setArmed(false)
          setError(audioFailTextRef.current())
        }
      }
      const playPrompt = async () => {
        if (currentItem.type !== "instruction") await beepRef.current()
        if (cancelled) return
        if (currentItem.audio_url) {
          const player = audio.current ?? new Audio()
          audio.current = player
          player.src = currentItem.audio_url.startsWith("/")
            ? `${import.meta.env.VITE_API_URL ?? ""}${currentItem.audio_url}`
            : currentItem.audio_url
          player.onended = ended
          player.onerror = failed
          // Re-entering an audio phase replays the current prompt. The server's
          // overall clock continues; waiting/preparation clocks never restart.
          void player.play().catch(failed)
        } else if (
          !speakEnglish(currentItem.text, { onEnd: ended, onError: failed })
        )
          failed()
      }
      void playPrompt().catch(failed)
    }
    if (
      phase === "answering" &&
      !accepted.current.has(currentItem.id) &&
      !recordingStarted.current.has(stageKey) &&
      !pendingDraft
    ) {
      if (
        (currentItem.type === "passage" ||
          currentItem.type === "repeat" ||
          currentItem.type === "question") &&
        owner
      ) {
        target.current = {
          owner,
          classroomCode: code,
          sessionId: sessionId,
          itemType: currentItem.type,
          itemId: currentItem.id,
          idempotencyKey: randomId(),
          mimeType: "audio/webm",
          durationS: 0,
          blob: new Blob(),
        }
        recordingStarted.current.add(stageKey)
        void recorderRef.current.start()
      }
    }
    return () => {
      cancelled = true
      audio.current?.pause()
      window.speechSynthesis?.cancel()
    }
  }, [
    stageKey,
    armed,
    draftsReady,
    pendingDraft,
    owner,
    code,
    sessionId,
    phase,
    latest,
    eventRef,
    accepted,
    recordingStarted,
    target,
    recorderRef,
    audio,
    beepRef,
    setArmed,
    setError,
  ])
}
