import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { ClassesService } from "@/client"
import type { StoredStudent } from "@/lib/classroom-student"
import { readSavedExpressions, saveSavedExpressions } from "@/lib/favorites"

const BATCH = 20

export function expressionFavoritesKey(code: string, studentId?: string) {
  return ["classroom", code, "expression-favorites", studentId] as const
}

/** 升级表达收藏走账号。这台浏览器里的旧收藏在打开页面时迁上去。 */
export function useExpressionFavorites(
  code: string,
  student: StoredStudent | null,
) {
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
        await ClassesService.addExpressionFavorites({
          code: classroomCode,
          requestBody: { texts: batch },
        })
        if (cancelled) return
        pending = pending.slice(batch.length)
        saveSavedExpressions(current, pending)
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
  }, [classroomCode, code, ownerId, queryClient])

  const add = useMutation({
    mutationFn: (texts: string[]) =>
      ClassesService.addExpressionFavorites({
        code: classroomCode,
        requestBody: { texts },
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
        favoriteId,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["classroom", code, "expression-favorites"],
      }),
  })

  return { query, add, remove }
}
