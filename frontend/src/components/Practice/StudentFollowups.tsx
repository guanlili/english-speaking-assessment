import { useMutation, useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useRef } from "react"
import { toast } from "sonner"
import { ClassesService } from "@/client"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

export function StudentFollowups({ code }: { code: string }) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const identity = useRef(localStorage.getItem("access_token"))
  const query = useQuery({
    queryKey: ["student", "followups", code],
    queryFn: () => ClassesService.listClassFollowups({ code }),
    refetchInterval: 20000,
  })
  const start = useMutation({
    mutationFn: (taskId: string) => {
      if (localStorage.getItem("access_token") !== identity.current)
        throw new Error("Session changed")
      return ClassesService.startClassFollowup({ code, taskId })
    },
    onSuccess: async (result) => {
      if (localStorage.getItem("access_token") !== identity.current) return
      await navigate({
        to: "/p/$code",
        params: { code },
        search: { session: result.session_id },
      })
    },
    onError: () =>
      toast.error(
        t({
          zh: "补练暂时无法开始，可能已撤销；请刷新后重试。",
          en: "Cannot start this task; it may have been withdrawn. Refresh and retry.",
        }),
      ),
  })
  if (query.isPending) return null
  if (query.isError)
    return (
      <section className="rounded-2xl border p-4">
        <p>
          {t({
            zh: "老师布置的补练暂时加载失败。",
            en: "Could not load your teacher's targeted practice.",
          })}
        </p>
        <Button
          className="mt-2 min-h-11"
          variant="outline"
          onClick={() => void query.refetch()}
        >
          {t({ zh: "重试", en: "Retry" })}
        </Button>
      </section>
    )
  const tasks = query.data ?? []
  if (!tasks.length) return null
  return (
    <section
      className="space-y-3 rounded-2xl border bg-card p-5"
      aria-label={t({ zh: "老师布置的补练", en: "Practice from your teacher" })}
    >
      <h2 className="font-semibold">
        {t({ zh: "老师布置的补练", en: "Practice from your teacher" })}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t({
          zh: "按老师建议巩固练习，不影响原考试成绩。显示最近 50 项任务。",
          en: "Practice your teacher's suggestions without changing original exam results. Showing your latest 50 tasks.",
        })}
      </p>
      {tasks.map((task) => {
        const progress = task.targets[0]
        const done = progress && progress.done_count === progress.total_count
        return (
          <article
            key={task.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"
          >
            <div className="min-w-0 break-words">
              <h3 className="font-medium">{task.title}</h3>
              <p className="text-sm text-muted-foreground">
                {progress?.done_count ?? 0}/{task.item_count}{" "}
                {progress?.has_pending
                  ? t({ zh: "评分中", en: "Scoring" })
                  : done
                    ? t({ zh: "已完成", en: "Completed" })
                    : null}
              </p>
            </div>
            {task.status === "followup_closed" ? (
              <span>{t({ zh: "已撤销", en: "Withdrawn" })}</span>
            ) : done && progress.session_id ? (
              <Button
                className="min-h-11"
                variant="outline"
                onClick={() =>
                  void navigate({
                    to: "/p/$code/result",
                    params: { code },
                    search: { session: progress.session_id ?? undefined },
                  })
                }
              >
                {t({ zh: "回看补练", en: "Review practice" })}
              </Button>
            ) : (
              <Button
                className="min-h-11"
                disabled={start.isPending}
                onClick={() => start.mutate(task.id)}
              >
                {t({
                  zh: progress?.session_id ? "继续补练" : "开始补练",
                  en: progress?.session_id
                    ? "Continue practice"
                    : "Start practice",
                })}
              </Button>
            )}
          </article>
        )
      })}
    </section>
  )
}
