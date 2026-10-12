import type { PlanItem } from "@/client"
import { speakEnglish } from "@/lib/tts"

const AUDIO_CHECK_TIMEOUT_MS = 15_000
const AUDIO_CHECK_CONCURRENCY = 4

export class ExamAudioCheckError extends Error {}

function checkFile(url: string, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const player = new Audio()
    let finished = false
    const finish = (error?: Error) => {
      if (finished) return
      finished = true
      clearTimeout(timer)
      signal.removeEventListener("abort", abort)
      player.onloadeddata = null
      player.onerror = null
      player.pause()
      player.removeAttribute("src")
      player.load()
      if (error) reject(error)
      else resolve()
    }
    const abort = () => finish(new ExamAudioCheckError("Audio check cancelled"))
    const timer = window.setTimeout(
      () => finish(new ExamAudioCheckError("Audio check timed out")),
      AUDIO_CHECK_TIMEOUT_MS,
    )
    player.onloadeddata = () => finish()
    player.onerror = () =>
      finish(new ExamAudioCheckError("Exam audio could not be loaded"))
    signal.addEventListener("abort", abort, { once: true })
    player.preload = "auto"
    player.src = url.startsWith("/")
      ? `${import.meta.env.VITE_API_URL ?? ""}${url}`
      : url
    player.load()
    if (signal.aborted) abort()
  })
}

function checkSpeech(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    let finished = false
    const finish = (error?: Error) => {
      if (finished) return
      finished = true
      clearTimeout(timer)
      signal.removeEventListener("abort", abort)
      window.speechSynthesis?.cancel()
      if (error) reject(error)
      else resolve()
    }
    const abort = () =>
      finish(new ExamAudioCheckError("Speech check cancelled"))
    const timer = window.setTimeout(
      () => finish(new ExamAudioCheckError("Speech check timed out")),
      AUDIO_CHECK_TIMEOUT_MS,
    )
    signal.addEventListener("abort", abort, { once: true })
    // Legacy snapshots may have no audio file. Test actual speech completion
    // inside the device-check gesture, before starting the server clock.
    try {
      if (
        !speakEnglish("Audio check.", {
          onEnd: () => finish(),
          onError: () =>
            finish(new ExamAudioCheckError("Speech is unavailable")),
        })
      )
        finish(new ExamAudioCheckError("Speech is unavailable"))
    } catch {
      finish(new ExamAudioCheckError("Speech is unavailable"))
    }
    if (signal.aborted) abort()
  })
}

export async function checkExamAudio(
  items: ReadonlyArray<Pick<PlanItem, "type" | "audio_url">>,
  signal: AbortSignal,
): Promise<void> {
  if (signal.aborted) throw new ExamAudioCheckError("Audio check cancelled")
  const prompts = items.filter((item) => item.type !== "passage")
  const urls = [
    ...new Set(
      prompts
        .map((item) => item.audio_url)
        .filter((url): url is string => !!url),
    ),
  ]
  let next = 0
  // Start the speech check synchronously, preserving the user's gesture.
  const speech = prompts.some((item) => !item.audio_url)
    ? checkSpeech(signal)
    : Promise.resolve()
  const workers = Array.from(
    { length: Math.min(AUDIO_CHECK_CONCURRENCY, urls.length) },
    async () => {
      while (next < urls.length) {
        const url = urls[next++]
        await checkFile(url, signal)
      }
    },
  )
  await Promise.all([speech, ...workers])
}
