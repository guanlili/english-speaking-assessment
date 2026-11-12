import { act, renderHook } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useRecorder } from "@/hooks/useRecorder"
import { I18nProvider } from "@/lib/i18n"

/**
 * useRecorder 是整条录音链路的唯一状态机：设备能力、权限、时长、中断、卸载。
 *
 * 这里测的不是覆盖率百分比，而是学生真实会撞上的失败路径 ——
 * 每一条都对应一句面向用户的文案，措辞一变，学生就不知道该干什么：
 * 「允许麦克风」和「没插耳机」是两种完全不同的处置动作，不能混成一句「录音失败」。
 *
 * 顺带锁定两条不显眼但会出事故的并发语义：
 * - 连续点击开始按钮只能启动一次（getUserMedia 是异步的，第二个点击不能重复占用麦克风）
 * - 录音中途中断的记录不得当作有效作答提交
 */

interface FakeTrack {
  readyState: string
  stop: () => void
  addEventListener: () => void
  removeEventListener: () => void
}

function makeStream() {
  const track: FakeTrack = {
    readyState: "live",
    stop: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
  }
  return {
    getTracks: () => [track],
    getAudioTracks: () => [track],
    active: true,
    track,
  }
}

/**
 * 可控的 MediaRecorder：真实实现里 onstart 是异步派发的，
 * 这里必须同样用 microtask，否则 `await start()` 会在状态切换前就返回。
 */
class FakeRecorder {
  static instances: FakeRecorder[] = []
  static isTypeSupported = () => true

  state: "inactive" | "recording" = "inactive"
  mimeType = "audio/webm"
  onstart: (() => void) | null = null
  onstop: (() => void) | null = null
  onerror: (() => void) | null = null
  ondataavailable: ((event: { data: Blob }) => void) | null = null

  constructor(_stream: unknown, options?: { mimeType?: string }) {
    if (options?.mimeType) this.mimeType = options.mimeType
    FakeRecorder.instances.push(this)
  }

  start() {
    this.state = "recording"
    Promise.resolve().then(() => this.onstart?.())
  }

  stop() {
    // 与真实实现一致：非 recording 状态下 stop 不派发 onstop，
    // 否则 useRecorder 的 generation 检查会拿到重复事件
    if (this.state !== "recording") return
    this.state = "inactive"
    this.onstop?.()
  }

  pause() {}
  resume() {}

  emitChunk() {
    this.ondataavailable?.({ data: new Blob(["chunk"]) })
  }

  fail() {
    this.onerror?.()
  }
}

const wrapper = ({ children }: { children: ReactNode }) => (
  <I18nProvider>{children}</I18nProvider>
)

let getUserMedia: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date("2026-01-01T00:00:00Z"))
  FakeRecorder.instances = []

  getUserMedia = vi.fn().mockResolvedValue(makeStream())
  Object.defineProperty(globalThis.navigator, "mediaDevices", {
    value: { getUserMedia },
    configurable: true,
    writable: true,
  })
  vi.stubGlobal("MediaRecorder", FakeRecorder)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe("useRecorder", () => {
  it("环境不支持录音时给出可执行的提示，而不是静默失败", async () => {
    vi.stubGlobal("MediaRecorder", undefined)
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: undefined,
      configurable: true,
      writable: true,
    })

    const { result } = renderHook(() => useRecorder(), { wrapper })
    await act(async () => {
      await result.current.start()
    })

    expect(result.current.deviceFault).toBe(true)
    expect(result.current.error).toContain("当前浏览器不支持录音")
    expect(getUserMedia).not.toHaveBeenCalled()
  })

  it("权限被拒时提示去地址栏开权限（NotAllowedError）", async () => {
    getUserMedia.mockRejectedValue(
      new DOMException("blocked", "NotAllowedError"),
    )

    const { result } = renderHook(() => useRecorder(), { wrapper })
    await act(async () => {
      await result.current.start()
    })

    expect(result.current.deviceFault).toBe(true)
    expect(result.current.error).toContain("需要允许麦克风")
    expect(result.current.status).toBe("idle")
  })

  it("没有可用麦克风设备时提示检查耳机连接（NotFoundError）", async () => {
    getUserMedia.mockRejectedValue(new DOMException("none", "NotFoundError"))

    const { result } = renderHook(() => useRecorder(), { wrapper })
    await act(async () => {
      await result.current.start()
    })

    expect(result.current.deviceFault).toBe(true)
    expect(result.current.error).toContain("未检测到麦克风设备")
  })

  it("有效录音完成后进入 ready 并只回调一次 onComplete", async () => {
    const onComplete = vi.fn()
    const { result } = renderHook(() => useRecorder({ onComplete }), {
      wrapper,
    })

    await act(async () => {
      await result.current.start()
    })
    expect(result.current.status).toBe("recording")

    // 越过 PRD US-02 的 1 秒下限
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200)
    })
    act(() => {
      FakeRecorder.instances[0].emitChunk()
    })
    act(() => {
      result.current.stop()
    })

    expect(result.current.status).toBe("ready")
    expect(result.current.recording?.blob).toBeInstanceOf(Blob)
    expect(onComplete).toHaveBeenCalledTimes(1)
  })

  it("录音过短时丢弃并提示重录，不提交作答", async () => {
    const onComplete = vi.fn()
    const onDiscard = vi.fn()
    const { result } = renderHook(
      () => useRecorder({ onComplete, onDiscard }),
      {
        wrapper,
      },
    )

    await act(async () => {
      await result.current.start()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400)
    })
    act(() => {
      FakeRecorder.instances[0].emitChunk()
    })
    act(() => {
      result.current.stop()
    })

    expect(result.current.status).toBe("idle")
    expect(result.current.error).toContain("录音太短")
    expect(onDiscard).toHaveBeenCalledWith("short")
    expect(onComplete).not.toHaveBeenCalled()
  })

  it("没有任何音频数据时同样按无效处理", async () => {
    const onComplete = vi.fn()
    const onDiscard = vi.fn()
    const { result } = renderHook(
      () => useRecorder({ onComplete, onDiscard }),
      {
        wrapper,
      },
    )

    await act(async () => {
      await result.current.start()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500)
    })
    // 故意不派发 ondataavailable：时长够了但 chunks 为空
    act(() => {
      result.current.stop()
    })

    expect(onDiscard).toHaveBeenCalledWith("short")
    expect(onComplete).not.toHaveBeenCalled()
  })

  it("到达 maxSeconds 时自动停止并正常提交", async () => {
    const onComplete = vi.fn()
    const { result } = renderHook(
      () => useRecorder({ maxSeconds: 2, onComplete }),
      {
        wrapper,
      },
    )

    await act(async () => {
      await result.current.start()
    })
    act(() => {
      FakeRecorder.instances[0].emitChunk()
    })
    // 计时器每 250ms 检查一次，2.5 秒足够越过 2 秒上限
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500)
    })

    expect(result.current.status).toBe("ready")
    expect(onComplete).toHaveBeenCalledTimes(1)
  })

  it("录音中途出错时按中断丢弃，不提交残缺数据", async () => {
    const onComplete = vi.fn()
    const onDiscard = vi.fn()
    const { result } = renderHook(
      () => useRecorder({ onComplete, onDiscard }),
      {
        wrapper,
      },
    )

    await act(async () => {
      await result.current.start()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200)
    })
    act(() => {
      FakeRecorder.instances[0].fail()
    })

    expect(result.current.error).toContain("录音中途中断")
    expect(onDiscard).toHaveBeenCalledWith("interrupted")
    expect(onComplete).not.toHaveBeenCalled()
  })

  it("连续点击开始只请求一次麦克风", async () => {
    const { result } = renderHook(() => useRecorder(), { wrapper })

    await act(async () => {
      await Promise.all([result.current.start(), result.current.start()])
    })

    expect(getUserMedia).toHaveBeenCalledTimes(1)
    expect(FakeRecorder.instances).toHaveLength(1)
  })

  it("reset 清空录音与错误，回到 idle", async () => {
    const { result } = renderHook(() => useRecorder(), { wrapper })

    await act(async () => {
      await result.current.start()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200)
    })
    act(() => {
      FakeRecorder.instances[0].emitChunk()
    })
    act(() => {
      result.current.stop()
    })
    expect(result.current.status).toBe("ready")

    act(() => {
      result.current.reset()
    })

    expect(result.current.status).toBe("idle")
    expect(result.current.recording).toBeNull()
    expect(result.current.error).toBeNull()
    expect(result.current.elapsed).toBe(0)
  })
})
