import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook } from "@testing-library/react"
import type { ReactNode } from "react"
import { toast } from "sonner"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { ExamStatus, PlanItem } from "@/client"
import type { AttemptSubmitTarget } from "@/hooks/useAttemptSubmit"
import { useRecordingFlow } from "@/hooks/useRecordingFlow"
import { I18nProvider } from "@/lib/i18n"
import {
  currentDraftOwner,
  deleteDraftsForItem,
  saveRecordingDraft,
} from "@/lib/recording-drafts"

/**
 * useRecordingFlow 是练习页的编排层：它不碰录音设备本身（那是 useRecorder），
 * 只管「录音开始到上传结束」这条链路上的状态归属。
 *
 * 测的是四类会真出事、但代码看不出问题的语义：
 *
 * 1. 目标钉住 —— 录音期间老师改指派，旧录音必须提交到旧题旧轮；
 * 2. 幂等 —— 上传失败后重传必须复用同一段音频和同一枚幂等键；
 * 3. 到期与撤销 —— 到点自动停、补练被撤销后彻底封口；
 * 4. 草稿并行 —— 落盘与上传同时跑，落盘没完成前不许放人走。
 *
 * 这些错了不会报错，只会安静地丢录音、重复计分或让学生提交到别的题上。
 */

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), warning: vi.fn(), success: vi.fn() },
}))

vi.mock("@/lib/recording-drafts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/recording-drafts")>()
  return {
    ...actual,
    currentDraftOwner: vi.fn(() => "owner-1"),
    saveRecordingDraft: vi.fn(),
    deleteDraftsForItem: vi.fn(),
  }
})

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

/** 可控 MediaRecorder：onstart 必须走 microtask，与真实实现一致。 */
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
    if (this.state !== "recording") return
    this.state = "inactive"
    this.onstop?.()
  }

  pause() {}
  resume() {}

  emitChunk() {
    this.ondataavailable?.({ data: new Blob(["chunk"]) })
  }
}

const ITEM: PlanItem = {
  type: "repeat",
  id: "item-1",
  text: "Hello world",
  suggested_seconds: 30,
}
const OTHER_ITEM: PlanItem = {
  type: "passage",
  id: "item-2",
  text: "Another",
  suggested_seconds: 60,
}
const EXAM: ExamStatus = {
  phase: "answering",
  item_remaining_seconds: 300,
  time_limit_minutes: 20,
  remaining_seconds: 1200,
  started: true,
  ended: false,
}

type IdSetter = (id: string | null) => void
let qc: QueryClient
let invalidateSpy: ReturnType<typeof vi.spyOn>
let submitAsync: ReturnType<
  typeof vi.fn<
    (
      variables: { blob: Blob; duration: number },
      targetOverride?: AttemptSubmitTarget,
    ) => Promise<unknown>
  >
>
let resetAttempt: ReturnType<typeof vi.fn<() => void>>
let setPinnedSessionId: ReturnType<typeof vi.fn<IdSetter>>
let setPinnedItemId: ReturnType<typeof vi.fn<IdSetter>>
let setFocusItemId: ReturnType<typeof vi.fn<IdSetter>>

interface FlowProps {
  code: string
  exam: ExamStatus | null
  examStarted: boolean
  examActive: boolean
  examEnded: boolean
  itemExpired: boolean
  prepDone: boolean
  currentItemDone: boolean
  currentItem: PlanItem | undefined
  sessionId: string | undefined
  syncedAt: number
  recordLimitSeconds: number
  acceptedExamItemsRef: { current: Set<string> }
  submitAsync: (
    variables: { blob: Blob; duration: number },
    targetOverride?: AttemptSubmitTarget,
  ) => Promise<unknown>
  submitting: boolean
  submitError: boolean
  submitErrorData: { status?: number; body?: { detail?: string } } | null
  resetAttempt: () => void
  setPinnedSessionId: (id: string | null) => void
  setPinnedItemId: (id: string | null) => void
  setFocusItemId: (id: string | null) => void
}

function makeProps(over: Partial<FlowProps> = {}): FlowProps {
  return {
    code: "CLS-1",
    exam: null,
    examStarted: false,
    examActive: false,
    examEnded: false,
    itemExpired: false,
    prepDone: true,
    currentItemDone: false,
    currentItem: ITEM,
    sessionId: "sess-1",
    syncedAt: Date.now(),
    recordLimitSeconds: 120,
    acceptedExamItemsRef: { current: new Set<string>() },
    submitAsync,
    submitting: false,
    submitError: false,
    submitErrorData: null,
    resetAttempt,
    setPinnedSessionId,
    setPinnedItemId,
    setFocusItemId,
    ...over,
  }
}

const wrapper = ({ children }: { children: ReactNode }) => (
  <I18nProvider>
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  </I18nProvider>
)

/** 录满 1.2 秒后停止，触发 onComplete。 */
async function recordFor(
  result: { current: ReturnType<typeof useRecordingFlow> },
  ms = 1200,
) {
  await act(async () => {
    result.current.startRecording()
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
  const instance = FakeRecorder.instances[FakeRecorder.instances.length - 1]
  act(() => {
    instance?.emitChunk()
  })
  act(() => {
    result.current.recorder.stop()
  })
  // onComplete 里起的异步链（落草稿 + 提交）必须在这里全部落在 act 内
  await flush()
}

/** 让 submitAsync / 草稿的异步链跑到底。 */
async function flush(times = 4) {
  for (let i = 0; i < times; i++) {
    await act(async () => {
      await Promise.resolve()
    })
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date("2026-01-01T00:00:00Z"))
  FakeRecorder.instances = []
  vi.stubGlobal("MediaRecorder", FakeRecorder)

  const getUserMedia = vi.fn().mockResolvedValue(makeStream())
  Object.defineProperty(globalThis.navigator, "mediaDevices", {
    value: { getUserMedia },
    configurable: true,
    writable: true,
  })

  qc = new QueryClient()
  invalidateSpy = vi.spyOn(qc, "invalidateQueries")
  submitAsync = vi.fn().mockResolvedValue({ id: "attempt-1" })
  resetAttempt = vi.fn()
  setPinnedSessionId = vi.fn()
  setPinnedItemId = vi.fn()
  setFocusItemId = vi.fn()

  vi.mocked(currentDraftOwner).mockReturnValue("owner-1")
  vi.mocked(saveRecordingDraft).mockResolvedValue("saved")
  vi.mocked(deleteDraftsForItem).mockResolvedValue(undefined)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe("useRecordingFlow —— 练习模式完整闭环", () => {
  it("练习模式提交成功后保留录音与目标供回放，清理由页面切题时执行", async () => {
    const acceptedExamItemsRef = { current: new Set<string>() }
    const { result } = renderHook(
      (props: FlowProps) => useRecordingFlow(props),
      {
        wrapper,
        initialProps: makeProps({ acceptedExamItemsRef }),
      },
    )

    await act(async () => {
      result.current.startRecording()
    })

    expect(result.current.recorder.status).toBe("recording")
    expect(result.current.recordingTargetRef.current).toMatchObject({
      itemId: "item-1",
      itemType: "repeat",
      sessionId: "sess-1",
    })
    // 幂等键在开始时就生成，重传要复用它
    expect(
      result.current.recordingTargetRef.current?.idempotencyKey,
    ).toBeTruthy()
    expect(setPinnedSessionId).toHaveBeenCalledWith("sess-1")
    expect(setPinnedItemId).toHaveBeenCalledWith("item-1")

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200)
    })
    act(() => {
      FakeRecorder.instances[0].emitChunk()
    })
    act(() => {
      result.current.recorder.stop()
    })
    await flush()

    expect(submitAsync).toHaveBeenCalledTimes(1)
    const [recording, target] = submitAsync.mock.calls[0]
    expect(recording.blob).toBeInstanceOf(Blob)
    expect(target!.itemId).toBe("item-1")

    // 练习模式不接受模考的「已接收」锁定
    expect(acceptedExamItemsRef.current.size).toBe(0)

    // 录音和目标都留着：页面此刻仍停在本题，学生要能听回放。
    // 清场由页面在切题/重录时显式做（PracticeNavigator.onSelect），
    // hook 在这里替页面清反而会把回放弄丢。
    expect(result.current.recorder.status).toBe("ready")
    expect(result.current.recordingTargetRef.current?.itemId).toBe("item-1")
    expect(setPinnedItemId).not.toHaveBeenCalledWith(null)
    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it("模考模式提交成功后写入已接收集合、复位 attempt 并清 focus", async () => {
    const acceptedExamItemsRef = { current: new Set<string>() }
    const { result } = renderHook(
      (props: FlowProps) => useRecordingFlow(props),
      {
        wrapper,
        initialProps: makeProps({
          exam: EXAM,
          examStarted: true,
          examActive: true,
          acceptedExamItemsRef,
        }),
      },
    )

    await recordFor(result)
    await flush()

    expect(submitAsync).toHaveBeenCalledTimes(1)
    expect(acceptedExamItemsRef.current.has("sess-1:item-1")).toBe(true)
    expect(resetAttempt).toHaveBeenCalledTimes(1)
    expect(setFocusItemId).toHaveBeenCalledWith(null)
    expect(result.current.recorder.status).toBe("idle")
  })
})

describe("useRecordingFlow —— 目标钉住与幂等", () => {
  it("录音期间计划刷新到别的题，提交的仍是开始时钉住的那一题", async () => {
    const { result, rerender } = renderHook(
      (props: FlowProps) => useRecordingFlow(props),
      { wrapper, initialProps: makeProps() },
    )

    await act(async () => {
      result.current.startRecording()
    })
    const pinnedKey = result.current.recordingTargetRef.current?.idempotencyKey

    // 老师在这一轮录音期间发布了新计划：页面上的 currentItem 变了
    rerender(makeProps({ currentItem: OTHER_ITEM }))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200)
    })
    act(() => {
      FakeRecorder.instances[0].emitChunk()
    })
    act(() => {
      result.current.recorder.stop()
    })
    await flush()

    const [, target] = submitAsync.mock.calls[0]
    expect(target!.itemId).toBe("item-1")
    expect(target!.idempotencyKey).toBe(pinnedKey)
  })

  it("录完即置 submittedRef，防止从结果页返回时被 allDone 再弹回去", async () => {
    const { result } = renderHook(
      (props: FlowProps) => useRecordingFlow(props),
      {
        wrapper,
        initialProps: makeProps(),
      },
    )

    expect(result.current.submittedRef.current).toBe(false)
    await recordFor(result)
    expect(result.current.submittedRef.current).toBe(true)
  })

  it("上传失败时保留原录音，重传复用同一段音频与同一枚幂等键", async () => {
    submitAsync.mockRejectedValueOnce(new Error("network"))
    const { result } = renderHook(
      (props: FlowProps) => useRecordingFlow(props),
      {
        wrapper,
        initialProps: makeProps(),
      },
    )

    await recordFor(result)
    await flush()

    // 失败路径：录音留在内存里供重传，pinned 不清、草稿不删
    expect(result.current.recorder.status).toBe("ready")
    expect(result.current.recorder.recording).toBeTruthy()
    expect(result.current.recordingTargetRef.current).not.toBeNull()
    expect(setPinnedItemId).not.toHaveBeenCalledWith(null)
    expect(deleteDraftsForItem).not.toHaveBeenCalled()

    const retryBlob = result.current.recorder.recording?.blob
    const retryKey = result.current.recordingTargetRef.current?.idempotencyKey

    act(() => {
      result.current.retrySubmit()
    })
    await flush()

    expect(submitAsync).toHaveBeenCalledTimes(2)
    const [recording, target] = submitAsync.mock.calls[1]
    expect(recording.blob).toBe(retryBlob)
    expect(target!.idempotencyKey).toBe(retryKey)
  })
})

describe("useRecordingFlow —— 到期与撤销", () => {
  it("模考到点时正在录音则立即停录音", async () => {
    const { result, rerender } = renderHook(
      (props: FlowProps) => useRecordingFlow(props),
      {
        wrapper,
        initialProps: makeProps({
          exam: EXAM,
          examStarted: true,
          examActive: true,
        }),
      },
    )

    await act(async () => {
      result.current.startRecording()
    })
    expect(result.current.recorder.status).toBe("recording")

    rerender(
      makeProps({
        exam: EXAM,
        examStarted: true,
        examActive: true,
        itemExpired: true,
      }),
    )
    await flush()

    expect(result.current.recorder.status).not.toBe("recording")
  })

  it("到点且已没有录音时复位并拉取服务端终态，同一题只做一次", async () => {
    const { result, rerender } = renderHook(
      (props: FlowProps) => useRecordingFlow(props),
      {
        wrapper,
        initialProps: makeProps({
          exam: EXAM,
          examStarted: true,
          examActive: true,
        }),
      },
    )

    rerender(
      makeProps({
        exam: EXAM,
        examStarted: true,
        examActive: true,
        itemExpired: true,
      }),
    )
    await flush()

    expect(setPinnedItemId).toHaveBeenCalledWith(null)
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["classroom", "CLS-1", "today"],
    })

    const callsAfterFirst = invalidateSpy.mock.calls.length
    rerender(
      makeProps({
        exam: EXAM,
        examStarted: true,
        examActive: true,
        itemExpired: true,
      }),
    )
    await flush()

    // expiredItemRef 挡住重复复位：同一题不会反复打服务端
    expect(invalidateSpy.mock.calls.length).toBe(callsAfterFirst)
    expect(result.current.recorder.status).toBe("idle")
  })

  it("补练被撤销后既不能开始录音也不能重传", async () => {
    const { result } = renderHook(
      (props: FlowProps) => useRecordingFlow(props),
      {
        wrapper,
        initialProps: makeProps({
          submitting: false,
          submitError: true,
          submitErrorData: {
            status: 409,
            body: { detail: "Followup cancelled" },
          },
        }),
      },
    )

    expect(result.current.submissionClosed).toBe(true)

    act(() => {
      result.current.startRecording()
    })
    expect(FakeRecorder.instances).toHaveLength(0)
    expect(result.current.recorder.status).toBe("idle")

    act(() => {
      result.current.retrySubmit()
    })
    expect(submitAsync).not.toHaveBeenCalled()
  })
})

describe("useRecordingFlow —— 草稿并行与离开保护", () => {
  it("录完即落草稿（与上传并行），服务器接受后删该题草稿", async () => {
    const { result } = renderHook(
      (props: FlowProps) => useRecordingFlow(props),
      {
        wrapper,
        initialProps: makeProps(),
      },
    )

    await recordFor(result)
    await flush()

    expect(saveRecordingDraft).toHaveBeenCalledTimes(1)
    const draft = vi.mocked(saveRecordingDraft).mock.calls[0][0]
    expect(draft).toMatchObject({
      owner: "owner-1",
      classroomCode: "CLS-1",
      sessionId: "sess-1",
      itemType: "repeat",
      itemId: "item-1",
    })
    // 草稿绑定原幂等键，恢复后才能接上同一次作答
    expect(draft.idempotencyKey).toBe(
      result.current.recordingTargetRef.current?.idempotencyKey ?? "unused",
    )
    expect(draft.durationS).toBeGreaterThan(1)

    expect(deleteDraftsForItem).toHaveBeenCalledTimes(1)
    expect(deleteDraftsForItem).toHaveBeenCalledWith(
      "owner-1",
      "CLS-1",
      "sess-1",
      "repeat",
      "item-1",
    )
  })

  it("草稿落盘未完成期间保持离开保护", async () => {
    let resolveDraft: (value: "saved" | "quota" | "unavailable") => void =
      () => {}
    vi.mocked(saveRecordingDraft).mockReturnValue(
      new Promise((resolve) => {
        resolveDraft = resolve
      }),
    )

    const { result } = renderHook(
      (props: FlowProps) => useRecordingFlow(props),
      {
        wrapper,
        initialProps: makeProps(),
      },
    )

    await recordFor(result)
    await flush()

    // 上传可能已经成功，但 IndexedDB 事务还没提交——此刻放人走会丢草稿
    expect(result.current.pendingBlockerActive).toBe(true)
    expect(result.current.leaveState).toBe("blocked")

    await act(async () => {
      resolveDraft("saved")
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(result.current.pendingBlockerActive).toBe(false)
  })

  it("本设备存不了草稿时只提示一次，不连录连弹", async () => {
    vi.mocked(saveRecordingDraft).mockResolvedValue("quota")

    const { result, rerender } = renderHook(
      (props: FlowProps) => useRecordingFlow(props),
      { wrapper, initialProps: makeProps() },
    )

    await recordFor(result)
    await flush()
    expect(vi.mocked(toast.warning)).toHaveBeenCalledTimes(1)

    // 第二次录音前把状态回到可录：清掉上一轮的 ready 与 submitError
    rerender(
      makeProps({
        submitError: false,
        submitErrorData: null,
        submitting: false,
      }),
    )
    act(() => {
      result.current.recorder.reset()
    })
    await recordFor(result)
    await flush()

    expect(vi.mocked(toast.warning)).toHaveBeenCalledTimes(1)
  })
})

describe("useRecordingFlow —— 失败提示文案", () => {
  it("评分队列繁忙（503）提示稍后重传", async () => {
    submitAsync.mockRejectedValueOnce(new Error("busy"))
    renderHook((props: FlowProps) => useRecordingFlow(props), {
      wrapper,
      initialProps: makeProps({
        submitError: true,
        submitErrorData: { status: 503 },
      }),
    })
    await flush()

    expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
      expect.stringContaining("评分队列繁忙"),
      expect.objectContaining({
        description: expect.stringContaining("录音已保留"),
      }),
    )
  })

  it("补练被撤销时明确告诉学生不能再提交，但已有记录保留", async () => {
    renderHook((props: FlowProps) => useRecordingFlow(props), {
      wrapper,
      initialProps: makeProps({
        submitError: true,
        submitErrorData: {
          status: 409,
          body: { detail: "Followup cancelled" },
        },
      }),
    })
    await flush()

    expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
      expect.stringContaining("补练已撤销"),
      expect.objectContaining({
        description: expect.stringContaining("已有记录仍会保留"),
      }),
    )
  })

  it("模考失败文案强调不能重录，练习失败文案允许重录", async () => {
    const practice = renderHook((props: FlowProps) => useRecordingFlow(props), {
      wrapper,
      initialProps: makeProps({ submitError: true }),
    })
    await flush()
    expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
      expect.stringContaining("上传失败"),
      expect.objectContaining({
        description: expect.stringContaining("重新录一次"),
      }),
    )

    vi.mocked(toast.error).mockClear()
    practice.unmount()

    renderHook((props: FlowProps) => useRecordingFlow(props), {
      wrapper,
      initialProps: makeProps({
        exam: EXAM,
        examStarted: true,
        submitError: true,
      }),
    })
    await flush()
    expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
      expect.stringContaining("上传失败"),
      expect.objectContaining({
        description: expect.stringContaining("模考不能重录"),
      }),
    )
  })
})
