import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import type { ExamStatus, PlanItem } from "@/client"
import type { AttemptSubmitTarget } from "@/hooks/useAttemptSubmit"
import { useRecorder } from "@/hooks/useRecorder"
import { useI18n } from "@/lib/i18n"
import {
  currentDraftOwner,
  deleteDraftsForItem,
  saveRecordingDraft,
} from "@/lib/recording-drafts"
import { randomId } from "@/utils"

/**
 * 练习页录音状态机：开始/结束/上传/重传的完整生命周期。
 *
 * - 录音开始时钉住 item_id / session_id / 题型 / 幂等键（recordingTargetRef）：
 *   录音期间老师切换指派不会让旧录音提交到新题新轮。
 * - 本次停留是否提交过录音（submittedRef）：防止从结果页回来时 allDone
 *   直接又跳回结果页。
 * - 模考已接收的提交键（acceptedExamItemsRef 由页面持有并传入）：任何已接收
 *   的提交都锁定（含 queued/failed），配合页面的 currentItemDone 判定。
 * - 到点（itemExpired）自动停录音/复位/拉取服务端终态。
 * - 录音草稿（批次08B）：录完即与上传并行落 IndexedDB（绑定账号/会话/题目/
 *   原幂等键，不含 token）；服务器接受后删该题草稿，失败保留供刷新后由
 *   DraftRecoveryCard 恢复上传；落盘未完成前离开保护不解除。
 */
export function useRecordingFlow({
  code,
  exam,
  examStarted,
  examActive,
  examEnded,
  itemExpired,
  prepDone,
  currentItemDone,
  currentItem,
  sessionId,
  syncedAt,
  recordLimitSeconds,
  acceptedExamItemsRef,
  submitAsync,
  submitting,
  submitError,
  submitErrorData,
  resetAttempt,
  setPinnedSessionId,
  setPinnedItemId,
  setFocusItemId,
}: {
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
  acceptedExamItemsRef: Readonly<{ current: Set<string> }>
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
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  // 录音开始时钉住 item_id / session_id / 题型：录音期间老师切换指派不影响旧录音
  const recordingTargetRef = useRef<AttemptSubmitTarget | null>(null)
  // 本次停留是否提交过录音：防止从结果页回来时 allDone 直接又跳回结果页
  const submittedRef = useRef(false)
  // 批次08B：草稿正在落盘（IndexedDB 写入未完成前保持离开保护——
  // 离开保护与数据落盘完成时机一致）
  const [draftFlushPending, setDraftFlushPending] = useState(false)
  // 存储不可用/配额不足的降级提示每次停留最多一次，避免连录连弹
  const draftWarnedRef = useRef(false)

  const recorder = useRecorder({
    deadlineAt:
      exam && examStarted
        ? syncedAt + (exam.item_remaining_seconds ?? 0) * 1000
        : undefined,
    // 模考下真实截止由 deadlineAt 精确钳制（开始录音时按绝对时间计算），
    // maxSeconds 只需给题目本身的作答上限
    maxSeconds: recordLimitSeconds,
    onComplete: (rec) => {
      submittedRef.current = true
      // 上传期间保留题面；模考上传成功即解除，不等待评分。
      if (currentItem) setPinnedItemId(currentItem.id)
      const target = recordingTargetRef.current
      // 录完即落草稿（与上传并行）：刷新/断网后仍可恢复。不保存 token，
      // 属主取 JWT sub；环境不可用时降级为仅内存重传。
      const owner = currentDraftOwner()
      if (target?.itemId && owner) {
        setDraftFlushPending(true)
        void saveRecordingDraft({
          owner,
          classroomCode: code,
          sessionId: target.sessionId ?? null,
          itemType: target.itemType,
          itemId: target.itemId,
          idempotencyKey: target.idempotencyKey ?? randomId(),
          mimeType: rec.blob.type || "audio/webm",
          durationS: rec.duration,
          blob: rec.blob,
        })
          .then((result) => {
            if (result !== "saved" && !draftWarnedRef.current) {
              draftWarnedRef.current = true
              toast.warning(
                t({
                  zh: "本设备无法暂存录音草稿（存储受限或空间不足），请保持页面打开，上传失败时尽快点重传",
                  en: "This device cannot keep a local recording draft (storage limited or full). Keep this page open and retry the upload soon if it fails.",
                }),
              )
            }
          })
          .finally(() => setDraftFlushPending(false))
      }
      // 使用录音开始时钉住的目标，避免录音期间计划刷新导致提交到新题新轮
      submitRecording(
        { blob: rec.blob, duration: rec.duration },
        target ?? undefined,
      )
    },
  })

  const submitRecording = (
    recording: { blob: Blob; duration: number },
    target?: AttemptSubmitTarget,
  ) => {
    // 统一走 submitAsync：服务器接受（2xx）后删除该题草稿；失败则草稿保留，
    // 刷新后由恢复卡片按原幂等键重传（不重复扣费）。普通练习与模考同规则。
    void submitAsync(recording, target)
      .then(() => {
        const accepted = target ?? recordingTargetRef.current
        const owner = currentDraftOwner()
        if (accepted?.itemId && owner) {
          void deleteDraftsForItem(owner, code, accepted.itemId)
        }
        if (!exam) return
        if (target)
          acceptedExamItemsRef.current.add(
            `${target.sessionId}:${target.itemId}`,
          )
        recorder.reset()
        resetAttempt()
        recordingTargetRef.current = null
        setPinnedItemId(null)
        setFocusItemId(null)
        void queryClient.invalidateQueries({
          queryKey: ["classroom", code, "today"],
        })
      })
      .catch(() => {
        // 原录音留给幂等重传；模考没有重新录制入口。
      })
  }

  // 开始录音前钉住当前题 / 会话 / 题型 / 幂等键 / 凭证；
  // 同时钉住会话：录音→上传→反馈期间老师发布新计划，练习页仍保持本轮，
  // 结果页也绑定这个实际完成的会话，不挂到新题新轮。
  const startRecording = () => {
    if (
      exam &&
      (!examStarted || examEnded || currentItemDone || !prepDone || itemExpired)
    )
      return
    recordingTargetRef.current = {
      itemType:
        (currentItem?.type as "passage" | "repeat" | "question") ?? "repeat",
      itemId: currentItem?.id ?? "",
      sessionId,
      idempotencyKey: randomId(),
    }
    setPinnedSessionId(sessionId ?? null)
    if (exam && currentItem) setPinnedItemId(currentItem.id)
    recorder.start()
  }

  // 重传：用相同幂等键重新提交同一段录音（断网/超时后恢复）
  const retrySubmit = () => {
    if (recorder.recording) {
      submittedRef.current = true
      submitRecording(
        {
          blob: recorder.recording.blob,
          duration: recorder.recording.duration,
        },
        recordingTargetRef.current ?? undefined,
      )
    }
  }

  // 录音/上传/失败待重传期间的离开保护判定（站内跳转 + 浏览器关闭/刷新）；
  // 草稿落盘未完成也保持保护——离开保护与数据落盘完成时机一致（批次08B）
  const pendingBlockerActive =
    recorder.status === "recording" ||
    submitting ||
    draftFlushPending ||
    (submitError && Boolean(recorder.recording))

  useEffect(() => {
    if (submitError) {
      const status = submitErrorData?.status
      if (status === 503) {
        toast.error(t({ zh: "评分队列繁忙", en: "Scoring queue is busy" }), {
          description: t({
            zh: "录音已保留，请稍后点重传",
            en: "Your recording is saved — tap retry in a moment",
          }),
        })
      } else {
        toast.error(t({ zh: "上传失败", en: "Upload failed" }), {
          description: t({
            zh: exam
              ? "录音已保留，请重传原录音；模考不能重录"
              : "录音已保留，可以点重传或重新录一次",
            en: exam
              ? "Your recording is saved. Retry the original upload; exam items cannot be re-recorded."
              : "Your recording is saved — retry the upload or record again",
          }),
        })
      }
    }
  }, [submitError, submitErrorData, t, exam])

  // 本地倒计时：以服务端 remaining_seconds 为准心，每秒递减仅作展示；
  // 未开考（确认页）不启动——服务端此刻也还没计时
  const expiredItemRef = useRef<string | null>(null)
  const recorderStop = recorder.stop
  const recorderReset = recorder.reset
  useEffect(() => {
    if (!examActive || !examStarted || !itemExpired || !currentItem) return
    if (recorder.status === "recording") {
      recorderStop()
      return
    }
    if (submitting || currentItemDone || (submitError && recorder.recording))
      return
    if (expiredItemRef.current === currentItem.id) return
    expiredItemRef.current = currentItem.id
    recorderReset()
    setPinnedItemId(null)
    void queryClient.invalidateQueries({
      queryKey: ["classroom", code, "today"],
    })
  }, [
    examActive,
    examStarted,
    itemExpired,
    currentItem,
    recorder.status,
    recorder.recording,
    recorderStop,
    recorderReset,
    submitting,
    currentItemDone,
    submitError,
    queryClient,
    code,
    setPinnedItemId,
  ])

  return {
    recorder,
    recordingTargetRef,
    submittedRef,
    startRecording,
    retrySubmit,
    pendingBlockerActive,
  }
}
