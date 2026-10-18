import { useCallback, useEffect, useRef, useState } from "react"
import { ClassesService } from "@/client"
import { Button } from "@/components/ui/button"
import { loadStudent } from "@/lib/classroom-student"
import {
  clearDeviceCheck,
  DEVICE_CHECK_TTL_MS,
  deviceCheckKey,
  readDeviceCheck,
  saveDeviceCheck,
} from "@/lib/device-preflight"
import { useI18n } from "@/lib/i18n"

const TEST_RECORDING_MS = 5000

export function DevicePreflight({ code }: { code: string }) {
  const student = loadStudent(code)
  const cacheKey = deviceCheckKey(student?.user_id, student?.id, code)
  return (
    <DevicePreflightCheck
      key={cacheKey ?? code.toUpperCase()}
      code={code}
      cacheKey={cacheKey}
    />
  )
}

function DevicePreflightCheck({
  code,
  cacheKey,
}: {
  code: string
  cacheKey: string | null
}) {
  const { t } = useI18n()
  const [passedAt, setPassedAt] = useState(() => readDeviceCheck(cacheKey))
  const [state, setState] = useState<
    "idle" | "recording" | "ready" | "passed" | "failed"
  >(passedAt ? "passed" : "idle")
  const [url, setUrl] = useState<string | null>(null)
  const [heard, setHeard] = useState(false)
  const [reportFailed, setReportFailed] = useState(false)
  const [checking, setChecking] = useState(false)
  const checkInFlight = useRef(false)
  const generation = useRef(0)
  const recording = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mounted = useRef(true)
  const active = useRef(false)
  const identity = useRef(localStorage.getItem("access_token"))
  const isCurrent = useCallback(
    () =>
      mounted.current &&
      identity.current === localStorage.getItem("access_token"),
    [],
  )
  const report = async (device_check: "passed" | "failed") => {
    if (!isCurrent()) return false
    if (device_check === "failed") {
      clearDeviceCheck(cacheKey)
      setPassedAt(null)
    }
    const currentGeneration = generation.current
    try {
      await ClassesService.reportClassroomActivity({
        code,
        requestBody: { activity: "entered", device_check },
      })
      if (!isCurrent() || currentGeneration !== generation.current) return false
      setReportFailed(false)
      return true
    } catch {
      if (isCurrent() && currentGeneration === generation.current)
        setReportFailed(true)
      return false
    }
  }
  useEffect(() => {
    if (passedAt === null) return
    const invalidate = () => {
      if (!isCurrent()) return
      clearDeviceCheck(cacheKey)
      setPassedAt(null)
      setState("idle")
    }
    const expire = () => {
      if (Date.now() < passedAt || Date.now() - passedAt >= DEVICE_CHECK_TTL_MS)
        invalidate()
    }
    const timer = window.setTimeout(
      expire,
      Math.max(0, passedAt + DEVICE_CHECK_TTL_MS - Date.now()),
    )
    document.addEventListener("visibilitychange", expire)
    const media = navigator.mediaDevices
    media?.addEventListener?.("devicechange", invalidate)
    return () => {
      clearTimeout(timer)
      document.removeEventListener("visibilitychange", expire)
      media?.removeEventListener?.("devicechange", invalidate)
    }
  }, [passedAt, cacheKey, isCurrent])
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      generation.current += 1
      if (timer.current) clearTimeout(timer.current)
      if (recording.current?.state === "recording") recording.current.stop()
      stream.current?.getTracks().forEach((track) => {
        track.stop()
      })
    }
  }, [])
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url)
    },
    [url],
  )
  async function start() {
    if (active.current || checkInFlight.current) return
    if (!isCurrent()) return
    clearDeviceCheck(cacheKey)
    setPassedAt(null)
    active.current = true
    const currentGeneration = ++generation.current
    let recorderFailed = false
    setHeard(false)
    setUrl(null)
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!isCurrent() || generation.current !== currentGeneration) {
        media.getTracks().forEach((track) => {
          track.stop()
        })
        return
      }
      stream.current = media
      const recorder = new MediaRecorder(media)
      recording.current = recorder
      const chunks: BlobPart[] = []
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data)
      }
      recorder.onstop = () => {
        media.getTracks().forEach((track) => {
          track.stop()
        })
        active.current = false
        if (
          !isCurrent() ||
          generation.current !== currentGeneration ||
          recorderFailed
        )
          return
        const blob = new Blob(chunks, { type: recorder.mimeType })
        if (!blob.size) {
          setState("failed")
          void report("failed")
          return
        }
        setUrl(URL.createObjectURL(blob))
        setState("ready")
      }
      recorder.onerror = () => {
        recorderFailed = true
        media.getTracks().forEach((track) => {
          track.stop()
        })
        active.current = false
        if (isCurrent() && generation.current === currentGeneration) {
          setState("failed")
          void report("failed")
        }
      }
      recorder.start()
      setState("recording")
      timer.current = setTimeout(() => {
        if (recorder.state === "recording") recorder.stop()
      }, TEST_RECORDING_MS)
    } catch {
      stream.current?.getTracks().forEach((track) => {
        track.stop()
      })
      active.current = false
      if (isCurrent() && generation.current === currentGeneration) {
        setState("failed")
        void report("failed")
      }
    }
  }
  if (state === "passed" && !reportFailed) {
    return (
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border bg-card px-5 py-3">
        <p role="status" className="text-sm text-muted-foreground">
          {t({
            zh: "试录、回放和课堂连接检查通过。",
            en: "Recording, playback and classroom connection checks passed.",
          })}
        </p>
        <Button
          variant="ghost"
          className="min-h-11"
          onClick={() => {
            clearDeviceCheck(cacheKey)
            setPassedAt(null)
            setState("idle")
            setUrl(null)
            setHeard(false)
          }}
        >
          {t({ zh: "重新检查", en: "Check again" })}
        </Button>
      </section>
    )
  }
  return (
    <section className="space-y-3 rounded-2xl border bg-card p-5">
      <h2 className="font-semibold">
        {t({ zh: "课前设备自检", en: "Before-class device check" })}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t({
          zh: "试说 5 秒，回放后确认听得清，再检查与课堂服务器的连接。试录仅留在本页，不上传录音，也不开始考试。",
          en: "Speak for 5 seconds, listen back and confirm you can hear clearly, then check the classroom connection. This recording stays on this page and does not start an exam.",
        })}
      </p>
      <Button
        className="min-h-11"
        disabled={state === "recording" || checking}
        onClick={() => void start()}
      >
        {state === "recording"
          ? t({
              zh: "试录中，请说一句英语…",
              en: "Recording — say a sentence…",
            })
          : t({ zh: "开始 5 秒试录", en: "Record a 5-second test" })}
      </Button>
      {url && (
        <>
          {/* biome-ignore lint/a11y/useMediaCaption: Local microphone self-test is replayed without transcription. */}
          <audio
            controls
            src={url}
            className="w-full"
            onEnded={() => setHeard(true)}
            onError={() => {
              setState("failed")
              void report("failed")
            }}
          />
          <Button
            variant="outline"
            className="min-h-11"
            disabled={!heard || checking || state === "recording"}
            onClick={async () => {
              if (checkInFlight.current || !isCurrent()) return
              checkInFlight.current = true
              setChecking(true)
              const currentGeneration = generation.current
              const checkedAt = Date.now()
              try {
                await ClassesService.readClassroomRevision({ code })
                if (!isCurrent() || currentGeneration !== generation.current)
                  return
                const reported = await report("passed")
                if (
                  reported &&
                  isCurrent() &&
                  currentGeneration === generation.current
                ) {
                  saveDeviceCheck(cacheKey, checkedAt)
                  setPassedAt(checkedAt)
                  setState("passed")
                  setUrl(null)
                }
              } catch {
                if (isCurrent() && currentGeneration === generation.current) {
                  setState("failed")
                  void report("failed")
                }
              } finally {
                checkInFlight.current = false
                if (isCurrent() && currentGeneration === generation.current)
                  setChecking(false)
              }
            }}
          >
            {t({
              zh: "听得清楚，检查课堂连接",
              en: "I can hear clearly — check connection",
            })}
          </Button>
        </>
      )}
      {state === "passed" && (
        <p role="status">
          {t({
            zh: "试录、回放和课堂连接检查通过。",
            en: "Recording, playback and classroom connection checks passed.",
          })}
        </p>
      )}
      {state === "failed" && (
        <p role="alert">
          {t({
            zh: "自检未通过，请检查麦克风权限、音量和网络后重试。",
            en: "Check microphone permissions, volume and network, then retry.",
          })}
        </p>
      )}
      {reportFailed && (
        <p role="alert">
          {t({
            zh: "自检结果尚未同步给老师，请重新检查课堂连接。",
            en: "Your check result has not reached your teacher. Retry the connection check.",
          })}
        </p>
      )}
    </section>
  )
}
