import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useRef, useState } from "react"
import {
  ApiError,
  ClassesService,
  type ComposerState,
  type DraftPublic,
} from "@/client"

/** Saves are serialized; revision conflicts stop rather than overwrite another device. */
export function useComposerAutosave(
  code: string,
  initial: DraftPublic | null | undefined,
  state: ComposerState,
  dirty: boolean,
  available: boolean,
) {
  const client = useQueryClient()
  const identityToken = useRef(localStorage.getItem("access_token"))
  const revision = useRef(initial?.revision ?? 0)
  const saved = useRef(
    initial ? JSON.stringify(initial.state) : JSON.stringify(state),
  )
  const latest = useRef(state)
  latest.current = state
  const edited = useRef(dirty)
  edited.current = dirty
  const blocked = useRef(false)
  const paused = useRef(false)
  const queue = useRef<Promise<void>>(Promise.resolve())
  const [status, setStatus] = useState<
    "saved" | "saving" | "error" | "conflict"
  >("saved")
  const signature = JSON.stringify(state)
  const flush = useCallback(() => {
    const work = queue.current.then(async () => {
      if (localStorage.getItem("access_token") !== identityToken.current)
        throw new Error("Session changed")
      if (blocked.current) throw new Error("Draft conflict")
      if (!available) throw new Error("Draft unavailable")
      if (!edited.current || saved.current === JSON.stringify(latest.current))
        return
      const value = latest.current
      const snapshot = JSON.stringify(value)
      setStatus("saving")
      try {
        const result = await ClassesService.saveComposerDraft({
          code,
          requestBody: { expected_revision: revision.current, state: value },
        })
        if (localStorage.getItem("access_token") !== identityToken.current)
          throw new Error("Session changed")
        revision.current = result.revision
        saved.current = snapshot
        client.setQueryData(["teacher", "composer-draft", code], result)
        setStatus("saved")
      } catch (error) {
        blocked.current = error instanceof ApiError && error.status === 409
        setStatus(blocked.current ? "conflict" : "error")
        throw error
      }
    })
    queue.current = work.catch(() => {})
    return work.then(() => revision.current)
  }, [available, client, code])
  useEffect(() => {
    if (
      !dirty ||
      paused.current ||
      blocked.current ||
      !available ||
      signature === saved.current
    )
      return
    setStatus("saving")
    const timer = setTimeout(() => {
      void flush().catch(() => {})
    }, 800)
    return () => clearTimeout(timer)
  }, [signature, dirty, available, flush])
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (edited.current && JSON.stringify(latest.current) !== saved.current)
        event.preventDefault()
    }
    window.addEventListener("beforeunload", warn)
    return () => {
      window.removeEventListener("beforeunload", warn)
      if (!paused.current && edited.current) void flush().catch(() => {})
    }
  }, [flush])
  return {
    status: available ? status : ("error" as const),
    unsaved: dirty && signature !== saved.current,
    flush,
    pause: () => {
      paused.current = true
    },
    resume: () => {
      paused.current = false
    },
    published: () => {
      revision.current = 0
      saved.current = JSON.stringify(latest.current)
      edited.current = false
      client.setQueryData(["teacher", "composer-draft", code], null)
      setStatus("saved")
      paused.current = false
    },
  }
}
