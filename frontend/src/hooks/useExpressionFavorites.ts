import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { toast } from "sonner"
import { ClassesService } from "@/client"
import type { StoredStudent } from "@/lib/classroom-student"
import {
  expressionsStillLocal,
  readSavedExpressions,
  saveSavedExpressions,
} from "@/lib/favorites"
import { useI18n } from "@/lib/i18n"

const BATCH = 20

export function expressionFavoritesKey(code: string, studentId?: string) {
  return ["classroom", code, "expression-favorites", studentId] as const
}

/** 升级表达收藏走账号。这台浏览器里的旧收藏在打开页面时迁上去。 */
export function useExpressionFavorites(
  code: string,
  student: StoredStudent | null,
) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const classroomCode = code.toUpperCase()
  const studentRef = useRef(student)
  studentRef.current = student
  const query = useQuery({
    queryKey: expressionFavoritesKey(code, student?.id),
    queryFn: () =>
      ClassesService.listMyExpressionFavorites({ code: classroomCode }),
    enabled: student !== null,
  })

  const ownerId = student?.user_id ?? student?.id ?? null
  useEffect(() => {
    const current = studentRef.current
    if (current === null || ownerId === null) return
    let cancelled = false
    const flush = async () => {
      let pending = readSavedExpressions(current)
      if (pending.length === 0) return
      while (pending.length > 0) {
        const batch = pending.slice(0, BATCH)
        const stored = await ClassesService.addExpressionFavorites({
          code: classroomCode,
          expressionFavoriteCreate: { texts: batch },
        })
        if (cancelled) return
        const before = pending.length
        pending = expressionsStillLocal(
          pending,
          stored.map((row) => row.text),
        )
        saveSavedExpressions(current, pending)
        if (pending.length === 0) break
        if (pending.length === before) {
          toast.message(
            t({
              zh: "收藏已满 50 条，多出来的仍留在这台设备上。",
              en: "Favorites are full at 50. The rest stay on this device.",
            }),
          )
          break
        }
      }
      await queryClient.invalidateQueries({
        queryKey: ["classroom", code, "expression-favorites"],
      })
    }
    void flush().catch(() => {
      // 留在本机，下次打开再迁
    })
    return () => {
      cancelled = true
    }
  }, [classroomCode, code, ownerId, queryClient, t])

  const add = useMutation({
    mutationFn: (texts: string[]) =>
      ClassesService.addExpressionFavorites({
        code: classroomCode,
        expressionFavoriteCreate: { texts },
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["classroom", code, "expression-favorites"],
      }),
  })

  const remove = useMutation({
    mutationFn: (favoriteId: string) =>
      ClassesService.removeExpressionFavorite({
        code: classroomCode,
        favorite_id: favoriteId,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["classroom", code, "expression-favorites"],
      }),
  })

  return { query, add, remove }
}
