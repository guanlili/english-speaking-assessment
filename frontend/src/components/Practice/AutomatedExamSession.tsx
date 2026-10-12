import { useMutation, useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import {
  ApiError,
  AttemptsService,
  ClassesService,
  type TodayPlan,
} from "@/client"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import { LanguageToggle } from "@/components/Common/LanguageToggle"
import ExamGroupedProgress from "@/components/Practice/ExamGroupedProgress"
import { Button } from "@/components/ui/button"
import { type Recording, useRecorder } from "@/hooks/useRecorder"
import { EXAM_AUDIO_UNLOCK_URL } from "@/lib/exam-audio"
import { checkExamAudio, ExamAudioCheckError } from "@/lib/exam-audio-check"
import { useI18n } from "@/lib/i18n"
import {
  currentDraftOwner,
  deleteRecordingDraft,
  draftKey,
  getRecordingDraft,
  listRecordingDrafts,
  type RecordingDraftInput,
  saveRecordingDraft,
} from "@/lib/recording-drafts"
import { ITEM_TYPE_LABELS } from "@/lib/terms"
import { speakEnglish } from "@/lib/tts"
import { randomId } from "@/utils"

// /attempts 422 的稳定 detail → 双语文案映射（后端 detail 是稳定标识不直出界面）
const UPLOAD_REJECT_LABELS: Record<string, { zh: string; en: string }> = {
  "录音太短（不足 1 秒），请再录一次": {
    zh: "录音不足 1 秒，服务器未接受；可重试或确认后放弃。",
    en: "The recording is under 1 second and was rejected. Retry or discard it after confirming.",
  },
  "音频为空，请再录一次": {
    zh: "录音内容为空，无法提交；可重试或确认后放弃。",
    en: "The recording is empty and cannot be submitted. Retry or discard it after confirming.",
  },
  "音频文件无效或损坏，请重新录音": {
    zh: "录音文件无效或损坏，无法提交；可重试或确认后放弃。",
    en: "The recording file is invalid or corrupted. Retry or discard it after confirming.",
  },
  "文件中没有音频音轨，请重新录音": {
    zh: "文件中没有音频音轨，无法提交；可重试或确认后放弃。",
    en: "The file has no audio track and cannot be submitted. Retry or discard it after confirming.",
  },
  "音轨数异常，请重新录音": {
    zh: "音频轨数异常，无法提交；可重试或确认后放弃。",
    en: "The audio tracks look abnormal. Retry or discard it after confirming.",
  },
}

export default function AutomatedExamSession({
  code,
  initialPlan,
  storageKey,
}: {
  code: string
  initialPlan: TodayPlan
  storageKey: string
}) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const query = useQuery({
    queryKey: ["automated-exam", code, initialPlan.session_id],
    queryFn: () =>
      ClassesService.readTodayPlan({ code, sessionId: initialPlan.session_id }),
    initialData: initialPlan,
    refetchInterval: 1000,
    retry: 1,
  })
  const plan = query.data
  const exam = plan.exam
  const item = plan.items[exam?.current_item_index ?? 0]
  const [armed, setArmed] = useState(false)
  const [enabling, setEnabling] = useState(false)
  const enablingRef = useRef(false)
  const audioCheck = useRef<AbortController | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [storageError, setStorageError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [restoredItem, setRestoredItem] = useState<string | null>(null)
  const draftsReady = restoredItem === item?.id
  const [pendingDraft, setPendingDraft] = useState<RecordingDraftInput | null>(
    null,
  )
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [notes, setNotes] = useState("")
  const context = useRef<AudioContext | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)
  const target = useRef<RecordingDraftInput | null>(null)
  const accepted = useRef(new Set(plan.attempts.map((a) => a.item_id)))
  const recordingStarted = useRef(new Set<string>())
  const latest = useRef({ plan, item, syncedAt: query.dataUpdatedAt })
  latest.current = { plan, item, syncedAt: query.dataUpdatedAt }
  const saving = useRef<Promise<void>>(Promise.resolve())
  const exitRequested = useRef(false)
  // 提前交题标记（存 itemId 防跨题残留）：录音上传成功后自动发 next
  const finishEarlyRef = useRef<string | null>(null)
  const phase = exam?.phase
  const stageKey = `${plan.session_id}:${item?.id}:${phase}`
  const owner = currentDraftOwner()

  const sendEvent = useMutation({
    mutationFn: (requestBody: {
      session_id: string
      item_id: string
      event: "audio-ended" | "next"
    }) =>
      ClassesService.advanceExamFlow({
        code,
        requestBody,
      }),
    retry: 2,
    onSuccess: () => {
      setError(null)
      void query.refetch()
    },
    onError: () =>
      setError(
        t({
          zh: "同步失败，请重试；服务器计时继续。",
          en: "Could not sync. Retry; the server clock continues.",
        }),
      ),
  })
  const eventRef = useRef(sendEvent.mutate)
  eventRef.current = sendEvent.mutate

  async function upload(input: RecordingDraftInput) {
    setBusy(true)
    setError(null)
    setPendingDraft(input)
    try {
      await AttemptsService.createAttemptUpload({
        formData: {
          audio: new File([input.blob], "exam.webm", {
            type: input.mimeType,
          }) as unknown as string,
          item_type: input.itemType,
          item_id: input.itemId,
          session_id: input.sessionId ?? undefined,
          idempotency_key: input.idempotencyKey,
          duration_s: input.durationS,
        },
      })
      accepted.current.add(input.itemId)
      await deleteRecordingDraft(draftKey(input))
      setPendingDraft(null)
      void query.refetch()
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        // 服务器明确拒绝内容（损坏/无音轨等）：重传同一文件无意义。
        // detail 是稳定标识，映射双语展示；未知 detail 走双语兜底。
        const detail = (err.body as { detail?: unknown } | null)?.detail
        const label =
          typeof detail === "string" ? UPLOAD_REJECT_LABELS[detail] : undefined
        setError(
          t(
            label ?? {
              zh: "录音无法提交，可重试或确认后放弃。",
              en: "The recording could not be submitted. Retry or discard it after confirming.",
            },
          ),
        )
      } else {
        setError(
          t({
            zh: "录音尚未提交，请重试。",
            en: "Recording has not been submitted. Please retry.",
          }),
        )
      }
    } finally {
      setBusy(false)
    }
  }
  const uploadRef = useRef(upload)
  uploadRef.current = upload
  // 退出唯一出口：先消费标记（防止跨题残留误触发），再等本机保存链清空后离页。
  function doExit() {
    exitRequested.current = false
    void saving.current.then(() =>
      navigate({ to: "/home/$code", params: { code } }),
    )
  }
  function persist(recording: Recording, complete: boolean) {
    const base = target.current
    if (!base) return
    const input = {
      ...base,
      blob: recording.blob,
      durationS: recording.duration,
      mimeType: recording.blob.type,
    }
    saving.current = saving.current.then(async () => {
      const result = await saveRecordingDraft(input)
      if (result !== "saved")
        setStorageError(
          t({
            zh: "浏览器未能保存录音，请保持页面打开并完成上传。",
            en: "Your browser could not save the recording. Keep this page open until upload completes.",
          }),
        )
      if (complete) {
        await uploadRef.current(input)
        if (exitRequested.current) doExit()
        else if (finishEarlyRef.current === input.itemId) {
          // 「说完了·下一题」只在上传成功后推进；失败回落到倒计时到点的
          // 常规路径（ready 页重试上传/下一题），不丢已保留的录音
          finishEarlyRef.current = null
          if (accepted.current.has(input.itemId))
            eventRef.current({
              session_id: input.sessionId ?? plan.session_id,
              item_id: input.itemId,
              event: "next",
            })
        }
      }
    })
  }
  const recorder = useRecorder({
    maxSeconds: item?.suggested_seconds,
    deadlineAt:
      query.dataUpdatedAt +
      Math.min(
        exam?.item_remaining_seconds ?? 0,
        exam?.remaining_seconds ?? 0,
      ) *
        1000,
    onComplete: (rec) => persist(rec, true),
    onProgress: (rec) => persist(rec, false),
    // 录音被判无效（过短/中断）不会触发 onComplete：退出请求在这里兑现，
    // 并提示本次录音未提交——不能把退出只挂在有效录音的完成回调上。
    onDiscard: (reason) => {
      // 无效录音（过短/中断）没有可交的作答：清掉提前交题标记，等倒计时
      finishEarlyRef.current = null
      if (!exitRequested.current) return
      if (reason === "short")
        toast.info(
          t({
            zh: "录音不足 1 秒未提交，已退出考试。",
            en: "The recording under 1 second was not submitted. You have left the exam.",
          }),
        )
      doExit()
    },
  })
  const recorderRef = useRef(recorder)
  recorderRef.current = recorder

  useEffect(() => {
    localStorage.setItem(storageKey, plan.session_id)
  }, [storageKey, plan.session_id])
  useEffect(() => {
    let cancelled = false
    async function restore() {
      if (owner) {
        const drafts = await listRecordingDrafts(owner, code)
        const found = drafts.find(
          (d) =>
            d.sessionId === plan.session_id &&
            d.itemId === item?.id &&
            !accepted.current.has(d.itemId),
        )
        if (found) {
          const saved = await getRecordingDraft(found.key)
          if (saved && !cancelled) setPendingDraft(saved)
        }
      }
      if (!cancelled) setRestoredItem(item?.id ?? null)
    }
    void restore()
    return () => {
      cancelled = true
    }
  }, [owner, code, plan.session_id, item?.id])

  const noteKey = `exam-note:${owner}:${plan.session_id}:${item?.id}`
  useEffect(() => {
    setNotes(localStorage.getItem(noteKey) ?? "")
  }, [noteKey])

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
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach((track) => {
        track.stop()
      })
      if (check.signal.aborted) return
      if (!exam?.started)
        await ClassesService.startExam({
          code,
          requestBody: { session_id: plan.session_id },
        })
      await query.refetch()
      setArmed(true)
    } catch (err) {
      if (check.signal.aborted) return
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
          setError(
            t({
              zh: "音频未播放完成，请启用声音后继续。",
              en: "Audio did not finish. Enable sound to continue.",
            }),
          )
        }
      }
      async function playPrompt() {
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
          sessionId: plan.session_id,
          itemType: currentItem.type,
          itemId: currentItem.id,
          idempotencyKey: randomId(),
          mimeType: "audio/webm",
          durationS: 0,
          blob: new Blob(),
        }
        void beepRef.current().then(() => {
          if (cancelled) return
          recordingStarted.current.add(stageKey)
          void recorderRef.current.start()
        })
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
    plan.session_id,
    phase,
    t,
  ])

  useEffect(() => {
    if (phase === "ready" || exam?.ended) recorder.stop()
  }, [phase, exam?.ended, recorder.stop])
  useEffect(() => {
    if (!exam?.ended || recorder.status === "recording" || busy) return
    void saving.current.then(() => {
      localStorage.removeItem(storageKey)
      void navigate({
        to: "/exam/$code/result",
        params: { code },
        search: { session: plan.session_id },
      })
    })
  }, [
    exam?.ended,
    recorder.status,
    busy,
    navigate,
    code,
    plan.session_id,
    storageKey,
  ])
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (recorderRef.current.status === "recording") e.preventDefault()
    }
    window.addEventListener("beforeunload", warn)
    return () => {
      window.removeEventListener("beforeunload", warn)
      audioCheck.current?.abort()
      audio.current?.pause()
      window.speechSynthesis?.cancel()
      void context.current?.close()
    }
  }, [])
  useEffect(() => {
    if (!exam?.started || exam.ended) return
    const report = () => {
      if (document.hidden)
        void ClassesService.reportExamViolation({
          code,
          requestBody: { session_id: plan.session_id },
        }).catch(() => undefined)
    }
    document.addEventListener("visibilitychange", report)
    return () => document.removeEventListener("visibilitychange", report)
  }, [code, plan.session_id, exam?.started, exam?.ended])

  // 说明题跳过：立即停朗读，服务器按「已读完」收尾本题并直接翻页（一键两事件）
  function skipInstruction() {
    const target = item
    if (!target) return
    window.speechSynthesis?.cancel()
    audio.current?.pause()
    sendEvent.mutate(
      { session_id: plan.session_id, item_id: target.id, event: "audio-ended" },
      {
        onSuccess: () => {
          sendEvent.mutate({
            session_id: plan.session_id,
            item_id: target.id,
            event: "next",
          })
        },
      },
    )
  }

  const labels: Record<string, { zh: string; en: string }> = {
    waiting: { zh: "请等待", en: "Please wait" },
    audio: { zh: "正在播放", en: "Playing audio" },
    preparing: { zh: "准备回答", en: "Prepare your answer" },
    buffer: { zh: "即将开始录音", en: "Recording starts shortly" },
    answering: {
      zh: "请作答 · 自动录音",
      en: "Answer now · recording automatically",
    },
    ready: { zh: "本题已结束", en: "Item finished" },
    finished: { zh: "考试已结束", en: "Exam finished" },
  }
  return (
    <main className="mx-auto min-h-svh max-w-4xl space-y-6 p-4 sm:p-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold">{t({ zh: "考试", en: "Exam" })}</h1>
        <LanguageToggle />
        <Button
          variant="outline"
          className="min-h-11"
          disabled={busy}
          onClick={() => {
            // 录音中：有效→上传后 doExit，无效→onDiscard 里 doExit；
            // 未在录音：直接退出。所有路径都消费 exitRequested，不跨题残留。
            exitRequested.current = true
            if (recorder.status === "recording") recorder.stop()
            else doExit()
          }}
        >
          {t({ zh: "保存并退出", en: "Save and exit" })}
        </Button>
      </header>
      <ExamGroupedProgress
        items={plan.items}
        currentIndex={exam?.current_item_index ?? 0}
      />
      <p>
        {t({ zh: "整场剩余", en: "Exam time remaining" })}:{" "}
        {exam?.remaining_seconds ?? 0}s
      </p>
      {!armed && !exam?.ended && (
        <section className="space-y-4 rounded-xl border p-5">
          <p>
            {t({
              zh: "允许麦克风和声音播放后，考试将自动播放题干并录音。退出不暂停计时。",
              en: "Allow microphone and sound. Prompts and recording run automatically. Leaving does not pause the clock.",
            })}
          </p>
          <Button
            className="min-h-11"
            disabled={enabling}
            onClick={() => void enable()}
          >
            {enabling
              ? t({
                  zh: "正在检查设备与题目音频…",
                  en: "Checking devices and exam audio…",
                })
              : t(
                  exam?.started
                    ? {
                        zh: "启用声音并继续考试",
                        en: "Enable sound and resume exam",
                      }
                    : {
                        zh: "检查设备并开始考试",
                        en: "Check devices and start exam",
                      },
                )}
          </Button>
        </section>
      )}
      {(error || recorder.error || query.isError) && (
        <p role="alert" className="text-destructive">
          {error ??
            recorder.error ??
            t({
              zh: "连接中断，服务器计时继续。正在重连…",
              en: "Connection lost. The server clock continues. Reconnecting…",
            })}
        </p>
      )}
      {storageError && (
        <p role="alert" className="text-destructive">
          {storageError}
        </p>
      )}
      {sendEvent.isError && (
        <Button
          className="min-h-11"
          disabled={sendEvent.isPending}
          onClick={() => {
            if (sendEvent.variables) sendEvent.mutate(sendEvent.variables)
          }}
        >
          {t({ zh: "重试同步", en: "Retry sync" })}
        </Button>
      )}
      {item && exam?.started && (
        <section className="space-y-5 rounded-xl border p-5 select-none">
          <h2 className="font-semibold">{t(ITEM_TYPE_LABELS[item.type])}</h2>
          {item.type === "repeat" ? (
            <p className="min-h-16 text-lg text-muted-foreground">
              {t({
                zh: "本题不显示文字：请听音频，听完后复述出来。",
                en: "No text for this item. Listen to the audio, then repeat what you heard.",
              })}
            </p>
          ) : (
            <p className="whitespace-pre-wrap break-words text-lg">
              {item.text}
            </p>
          )}
          {item.cue_card_bullets?.length ? (
            <ul className="list-disc pl-5">
              {item.cue_card_bullets.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          ) : null}
          <p role="status">
            {t(
              labels[phase ?? ""] ?? { zh: "等待开考", en: "Waiting to start" },
            )}{" "}
            {exam?.phase_remaining_seconds
              ? `${exam.phase_remaining_seconds}s`
              : ""}
          </p>
          {item.type === "instruction" &&
            (phase === "waiting" || phase === "audio") && (
              <Button
                className="min-h-11 px-8 text-base"
                disabled={busy || sendEvent.isPending}
                onClick={skipInstruction}
              >
                {t({ zh: "已读完 · 跳过说明", en: "Skip instructions" })}
              </Button>
            )}
          {phase === "answering" &&
            recorder.status === "recording" &&
            !pendingDraft && (
              <div className="grid justify-items-center gap-1">
                <Button
                  className="min-h-11 px-8 text-base"
                  disabled={busy || sendEvent.isPending || recorder.elapsed < 1}
                  onClick={() => {
                    finishEarlyRef.current = item.id
                    recorder.stop()
                  }}
                >
                  {t({ zh: "我说完了", en: "I'm done" })}
                </Button>
                <p className="text-xs text-muted-foreground">
                  {t({
                    zh: "说完即点，无需等倒计时走完",
                    en: "Tap as soon as you finish — no need to wait out the timer",
                  })}
                </p>
              </div>
            )}
          {item.type === "question" && (
            <label className="grid gap-2">
              {t({
                zh: "准备笔记（不计分）",
                en: "Preparation notes (not graded)",
              })}
              <textarea
                className="min-h-32 w-full rounded-md border p-3 text-base select-text"
                value={notes}
                onChange={(e) => {
                  setNotes(e.target.value)
                  localStorage.setItem(noteKey, e.target.value)
                }}
              />
            </label>
          )}
          {pendingDraft && (
            <div className="flex flex-wrap gap-2">
              <Button
                className="min-h-11"
                disabled={busy}
                onClick={() => void upload(pendingDraft)}
              >
                {t({
                  zh: "恢复并提交保留的录音",
                  en: "Restore and submit saved recording",
                })}
              </Button>
              <Button
                variant="outline"
                className="min-h-11"
                disabled={busy}
                onClick={() => setConfirmDiscard(true)}
              >
                {t({ zh: "放弃这段录音", en: "Discard this recording" })}
              </Button>
            </div>
          )}
          {recorder.error && phase === "answering" && !pendingDraft && (
            <Button className="min-h-11" onClick={() => void recorder.start()}>
              {t({ zh: "重试麦克风", en: "Retry microphone" })}
            </Button>
          )}
          {phase === "ready" && (
            <Button
              className="min-h-11"
              disabled={
                busy ||
                sendEvent.isPending ||
                recorder.status === "recording" ||
                !!pendingDraft
              }
              onClick={() => {
                const event = {
                  session_id: plan.session_id,
                  item_id: item.id,
                  event: "next" as const,
                }
                void saving.current.then(() => eventRef.current(event))
              }}
            >
              {t({ zh: "下一题", en: "Next" })}
            </Button>
          )}
        </section>
      )}
      <ConfirmDialog
        open={confirmDiscard}
        title={t({ zh: "放弃这段录音？", en: "Discard this recording?" })}
        description={t({
          zh: "放弃后本题将没有作答记录，无法恢复。仅在上传持续失败时使用。",
          en: "This item will have no answer record and cannot be recovered. Use only when uploading keeps failing.",
        })}
        confirmText={t({ zh: "放弃录音", en: "Discard recording" })}
        onOpenChange={setConfirmDiscard}
        onConfirm={async () => {
          if (pendingDraft) await deleteRecordingDraft(draftKey(pendingDraft))
          setPendingDraft(null)
          setError(null)
          setConfirmDiscard(false)
        }}
      />
    </main>
  )
}
