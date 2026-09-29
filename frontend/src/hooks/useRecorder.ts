import { useCallback, useEffect, useRef, useState } from "react"

export type RecorderStatus = "idle" | "recording" | "ready"

export interface Recording {
  blob: Blob
  duration: number
}

export interface UseRecorderOptions {
  /** 一条有效录音完成时触发，恰好一次（在 onstop 里调用）。 */
  onComplete?: (recording: Recording) => void
}

// PRD §9：单条音频上限 60 秒，超时自动停
export const MAX_RECORD_SECONDS = 60
// PRD US-02：短于 1 秒不打分
export const MIN_RECORD_SECONDS = 1

function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]
  for (const type of candidates) {
    if (
      typeof MediaRecorder !== "undefined" &&
      MediaRecorder.isTypeSupported(type)
    ) {
      return type
    }
  }
  return ""
}

export function useRecorder(options: UseRecorderOptions = {}) {
  const [status, setStatus] = useState<RecorderStatus>("idle")
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [recording, setRecording] = useState<Recording | null>(null)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const startedAtRef = useRef(0)
  const timerRef = useRef<number | null>(null)
  const onCompleteRef = useRef(options.onComplete)
  onCompleteRef.current = options.onComplete
  // 卸载标志：录音中离开页面时，onstop 不再提交幽灵作答
  const disposedRef = useRef(false)
  // 同步并发保护：getUserMedia 是异步的，连续点击期间用 ref 挡住第二个 start
  const startingRef = useRef(false)

  const cleanup = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
    streamRef.current?.getTracks().forEach((track) => {
      track.stop()
    })
    streamRef.current = null
    recorderRef.current = null
  }, [])

  const stop = useCallback(() => {
    const recorder = recorderRef.current
    if (recorder && recorder.state === "recording") {
      recorder.stop()
    }
  }, [])

  const reset = useCallback(() => {
    setStatus("idle")
    setElapsed(0)
    setError(null)
    setRecording(null)
  }, [])

  const start = useCallback(async () => {
    // 同步并发保护：getUserMedia 未返回前第二个 start 直接忽略
    if (startingRef.current) return
    if (recorderRef.current?.state === "recording") return
    startingRef.current = true
    setError(null)
    setRecording(null)
    setElapsed(0)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      })
      // await 期间卸载（权限弹窗未响应/用户已离开）：释放麦克风，不建 recorder
      if (disposedRef.current) {
        stream.getTracks().forEach((track) => {
          track.stop()
        })
        return
      }
      streamRef.current = stream
      const mimeType = pickMimeType()
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream)
      const blobType = mimeType || "audio/webm"

      chunksRef.current = []
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data)
        }
      }
      recorder.onstop = () => {
        // 卸载中（用户离开页面）：释放麦克风但不提交幽灵作答
        if (disposedRef.current) {
          cleanup()
          return
        }
        const duration = (Date.now() - startedAtRef.current) / 1000
        cleanup()
        // PRD US-02：空文件或短于 1 秒不打分，提示再录
        if (duration < MIN_RECORD_SECONDS || chunksRef.current.length === 0) {
          setStatus("idle")
          setError("录音太短（不足 1 秒），请再录一次")
          return
        }
        const blob = new Blob(chunksRef.current, { type: blobType })
        const rec = { blob, duration }
        setRecording(rec)
        setStatus("ready")
        onCompleteRef.current?.(rec)
      }

      startedAtRef.current = Date.now()
      setStatus("recording")
      recorder.start(250)
      recorderRef.current = recorder
      timerRef.current = window.setInterval(() => {
        const seconds = (Date.now() - startedAtRef.current) / 1000
        setElapsed(seconds)
        if (seconds >= MAX_RECORD_SECONDS) {
          stop()
        }
      }, 250)
    } catch (err) {
      cleanup()
      setStatus("idle")
      const name = err instanceof DOMException ? err.name : ""
      // PRD US-02：拒绝授权时说明原因，不提交空文件
      if (name === "NotAllowedError" || name === "SecurityError") {
        setError(
          "需要允许麦克风：请在浏览器地址栏的权限设置中允许麦克风，然后重试",
        )
      } else {
        setError("无法访问麦克风，请检查耳机是否插好")
      }
    } finally {
      startingRef.current = false
    }
  }, [cleanup, stop])

  // 卸载时释放麦克风。注意 StrictMode 会先「挂载→清理→再挂载」：
  // 清理里置 disposed=true，再挂载时必须复位为 false，否则 start 会误判为已卸载。
  useEffect(() => {
    disposedRef.current = false
    return () => {
      disposedRef.current = true
      const recorder = recorderRef.current
      if (recorder && recorder.state === "recording") {
        recorder.stop()
      }
      cleanup()
    }
  }, [cleanup])

  return { status, elapsed, error, recording, start, stop, reset }
}
