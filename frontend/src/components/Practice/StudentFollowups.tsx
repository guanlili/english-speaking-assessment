import { useMutation, useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { ClassesService } from "@/client"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useI18n } from "@/lib/i18n"
import { pollWhileVisible } from "@/lib/poll"

const PAGE_SIZE = 10

export function StudentFollowups({ code }: { code: string }) {
  return <StudentFollowupsList key={code} code={code} />
}

function StudentFollowupsList({ code }: { code: string }) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const identity = useRef(localStorage.getItem("access_token"))
  const [status, setStatus] = useState<"active" | "history">("active")
  const [offset, setOffset] = useState(0)
  const query = useQuery({
    queryKey: ["student", "followups", code, status, offset],
    queryFn: () =>
      ClassesService.listClassFollowups({
        code,
        status,
        offset,
        limit: PAGE_SIZE + 1,
      }),
    refetchInterval: pollWhileVisible(20000),
  })
  // A scoring update can move the last task on this page to history.
  useEffect(() => {
    if (
      query.isSuccess &&
      !query.isFetching &&
      query.data.length === 0 &&
      offset > 0
    )
      setOffset((value) => Math.max(0, value - PAGE_SIZE))
  }, [query.isSuccess, query.isFetching, query.data, offset])
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
  const tasks = (query.data ?? []).slice(0, PAGE_SIZE)
  const hasNext = (query.data?.length ?? 0) > PAGE_SIZE
  if (
    query.isSuccess &&
    status === "active" &&
    offset === 0 &&
    tasks.length === 0
  ) {
    return (
      <section
        className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border bg-card px-5 py-3"
        aria-label={t({
          zh: "老师布置的补练",
          en: "Practice from your teacher",
        })}
      >
        <p className="text-sm text-muted-foreground">
          {t({ zh: "暂无待完成补练。", en: "No practice left to do." })}
        </p>
        <Button
          variant="ghost"
          className="min-h-11"
          onClick={() => setStatus("history")}
        >
          {t({ zh: "查看补练历史", en: "View practice history" })}
        </Button>
      </section>
    )
  }
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
          zh: "按老师建议巩固练习，不影响原考试成绩。已完成和已撤销的任务可在历史中查看。",
          en: "Practice your teacher's suggestions without changing original exam results. Completed and withdrawn tasks are in History.",
        })}
      </p>
      <Tabs
        value={status}
        onValueChange={(value) => {
          setStatus(value === "history" ? "history" : "active")
          setOffset(0)
        }}
      >
        <TabsList
          className="h-auto"
          aria-label={t({ zh: "补练状态", en: "Practice status" })}
        >
          <TabsTrigger className="min-h-11" value="active">
            {t({ zh: "待完成", en: "To do" })}
          </TabsTrigger>
          <TabsTrigger className="min-h-11" value="history">
            {t({ zh: "历史", en: "History" })}
          </TabsTrigger>
        </TabsList>
        <TabsContent value={status} className="space-y-3">
          {query.isError ? (
            <div role="alert">
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
            </div>
          ) : query.isPending ? (
            <p role="status">{t({ zh: "正在加载…", en: "Loading…" })}</p>
          ) : tasks.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {status === "active"
                ? t({ zh: "暂无待完成补练。", en: "No practice left to do." })
                : t({ zh: "暂无补练历史。", en: "No practice history yet." })}
            </p>
          ) : (
            tasks.map((task) => {
              const progress = task.targets[0]
              const done =
                progress && progress.done_count === progress.total_count
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
                        : progress?.has_failures
                          ? t({
                              zh: "评分失败，请重试",
                              en: "Scoring failed. Please retry.",
                            })
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
            })
          )}
          {(offset > 0 || hasNext) && (
            <nav
              className="flex flex-wrap items-center gap-3"
              aria-label={t({ zh: "补练分页", en: "Practice pages" })}
            >
              <Button
                className="min-h-11"
                variant="outline"
                disabled={offset === 0 || query.isFetching}
                onClick={() =>
                  setOffset((value) => Math.max(0, value - PAGE_SIZE))
                }
              >
                {t({ zh: "上一页", en: "Previous" })}
              </Button>
              <span className="text-sm" aria-live="polite">
                {t({
                  zh: `第 ${offset / PAGE_SIZE + 1} 页`,
                  en: `Page ${offset / PAGE_SIZE + 1}`,
                })}
              </span>
              <Button
                className="min-h-11"
                variant="outline"
                disabled={!hasNext || query.isFetching || query.isError}
                onClick={() => setOffset((value) => value + PAGE_SIZE)}
              >
                {t({ zh: "下一页", en: "Next" })}
              </Button>
            </nav>
          )}
        </TabsContent>
      </Tabs>
    </section>
  )
}
