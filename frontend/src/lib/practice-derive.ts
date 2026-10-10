import type { BiString } from "./bi.ts"
import { nextUnansweredIndex } from "./practice-navigation.ts"

/**
 * 练习页派生计算（纯函数层，批次 10-10 拆分）：
 * 从 p.$code.index.tsx 抽出的无副作用计算——提交终态、题目合并、
 * attempt 索引、当前题定位、完成后下一题解析、离开保护提示选择。
 * 状态/请求/考试时钟仍归页面，这里只做可单测的数据推导；
 * 入参取最小结构（{ id } / { item_id }），不绑死 client 生成类型。
 */

/** 提交终态：done/failed 之后不再等待评分或轮询 */
export function isAttemptTerminal(status: string | undefined): boolean {
  return status === "done" || status === "failed"
}

/** 今日计划题 + 追加换来的题（US-06 换一题）：同 id 去重，保持计划顺序 */
export function mergeItemsWithExtra<T extends { id: string }>(
  planItems: readonly T[],
  extraQuestion: T | null,
): T[] {
  const merged = [...planItems]
  if (extraQuestion && !merged.some((item) => item.id === extraQuestion.id)) {
    merged.push(extraQuestion)
  }
  return merged
}

/** item_id → attempt 索引（后写覆盖前写，与 attempts 列表顺序一致） */
export function buildAttemptByItem<T extends { item_id: string }>(
  attempts: readonly T[],
): Map<string, T> {
  const map = new Map<string, T>()
  for (const attempt of attempts) {
    map.set(attempt.item_id, attempt)
  }
  return map
}

export interface PracticeIndexInput<T extends { id: string }> {
  items: readonly T[]
  /** 结果页「重练最弱一题」等手动定位 */
  focusItemId: string | null
  /** 提交后钉住当前题（查看反馈期间不被计划刷新拽走），点「下一题」解除 */
  pinnedItemId: string | null
  /** 模考服务端题序（exam.current_item_index）；非模考传 null */
  examIndex: number | null
  isItemDone: (item: T) => boolean
}

/** 当前题定位优先级：钉住题 > 模考题序 > 手动聚焦 > 第一道未完成（全完成回退末题） */
export function resolvePracticeIndex<T extends { id: string }>(
  input: PracticeIndexInput<T>,
): number {
  const { items, focusItemId, pinnedItemId, examIndex, isItemDone } = input
  if (pinnedItemId) {
    const pinnedIndex = items.findIndex((item) => item.id === pinnedItemId)
    if (pinnedIndex >= 0) return pinnedIndex
  }
  if (examIndex !== null) return Math.min(examIndex, items.length - 1)
  if (focusItemId) {
    const focusIndex = items.findIndex((item) => item.id === focusItemId)
    if (focusIndex >= 0) return focusIndex
  }
  const firstUndone = items.findIndex((item) => !isItemDone(item))
  if (firstUndone === -1) return items.length - 1
  return firstUndone
}

/**
 * 完成当前题后的下一道聚焦题 id：从当前题之后绕圈找未完成
 * （顺序规则复用 practice-navigation 的 nextUnansweredIndex）；
 * 全部完成返回 null，调用方据此跳结果页。
 * isCompleted 由调用方给定，需包含「刚完成的这一题」
 * （乐观 ack / 刚终态的 attempt 当下还不在旧状态索引里）。
 */
export function nextItemIdAfterCompletion<T extends { id: string }>(
  items: readonly T[],
  currentIndex: number,
  isCompleted: (item: T) => boolean,
): string | null {
  const itemIds = items.map((item) => item.id)
  const completedIds = new Set(items.filter(isCompleted).map((item) => item.id))
  const index = nextUnansweredIndex(itemIds, currentIndex, completedIds)
  return index >= 0 ? (itemIds[index] ?? null) : null
}

/** 录音/上传/失败待重传期间离开保护的提示文案（按状态三选一，双语） */
export function blockerNotice(
  recorderStatus: string,
  submitting: boolean,
  inExam: boolean,
): BiString {
  if (recorderStatus === "recording") {
    return {
      zh: "正在录音，先结束或确认录音后再离开",
      en: "Recording in progress — stop or confirm the recording before leaving",
    }
  }
  if (submitting) {
    return {
      zh: "录音正在上传，请稍候或完成后再离开",
      en: "Your recording is uploading — please wait or finish before leaving",
    }
  }
  return inExam
    ? {
        zh: "录音上传失败，请重传原录音",
        en: "Upload failed — retry the original recording",
      }
    : {
        zh: "录音上传失败，请先重传或重录",
        en: "Upload failed — please retry the upload or re-record first",
      }
}
