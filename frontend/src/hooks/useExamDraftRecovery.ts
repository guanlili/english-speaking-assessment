import { type RefObject, useEffect, useState } from "react"
import {
  getRecordingDraft,
  listRecordingDrafts,
  type RecordingDraftInput,
} from "@/lib/recording-drafts"

export function useExamDraftRecovery({
  owner,
  code,
  sessionId,
  itemId,
  accepted,
  setPendingDraft,
}: {
  owner: string | null
  code: string
  sessionId: string
  itemId: string | undefined
  accepted: RefObject<Set<string>>
  setPendingDraft: (draft: RecordingDraftInput | null) => void
}) {
  const [restoredItem, setRestoredItem] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    async function restore() {
      if (owner) {
        const drafts = await listRecordingDrafts(owner, code)
        const found = drafts.find(
          (d) =>
            d.sessionId === sessionId &&
            d.itemId === itemId &&
            !accepted.current.has(d.itemId),
        )
        if (found) {
          const saved = await getRecordingDraft(found.key)
          if (saved && !cancelled) setPendingDraft(saved)
        }
      }
      if (!cancelled) setRestoredItem(itemId ?? null)
    }
    void restore()
    return () => {
      cancelled = true
    }
  }, [owner, code, sessionId, itemId, accepted, setPendingDraft])
  return restoredItem === itemId
}
