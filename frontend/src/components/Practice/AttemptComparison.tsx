import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { AttemptsService } from "@/client"
import AttemptAudio from "@/components/Practice/AttemptAudio"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
export function AttemptComparison({ attemptId }: { attemptId: string }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const query = useQuery({
    queryKey: ["attempt-comparison", attemptId],
    queryFn: () => AttemptsService.readAttemptComparison({ attemptId }),
    enabled: open,
    retry: false,
  })
  return (
    <section className="space-y-3">
      <Button
        variant="outline"
        className="min-h-11"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {t({
          zh: "对比首次与最近一次作答",
          en: "Compare first and latest answers",
        })}
      </Button>
      {open && (
        <>
          <p className="text-sm text-muted-foreground">
            {t({
              zh: "同一轮同一道题的已出分练习。参考分的变化不代表正式能力评级。",
              en: "Scored answers to the same item in this practice session. Changes in reference scores are not an official proficiency assessment.",
            })}
          </p>
          {query.isPending ? (
            <p role="status">{t({ zh: "正在加载…", en: "Loading…" })}</p>
          ) : query.isError ? (
            <Button variant="outline" onClick={() => void query.refetch()}>
              {t({
                zh: "对比暂不可用，重试",
                en: "Comparison unavailable. Retry",
              })}
            </Button>
          ) : !query.data?.length ? (
            <p>
              {t({
                zh: "再练一次并完成评分后，即可对比两次录音和表达。",
                en: "Practice again and wait for scoring to compare recordings and wording.",
              })}
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {query.data.map((attempt, index) => (
                <article
                  className="min-w-0 space-y-3 rounded-xl border p-4"
                  key={attempt.id}
                >
                  <h3 className="font-semibold">
                    {index === 0
                      ? t({ zh: "首次作答", en: "First answer" })
                      : t({ zh: "最近一次", en: "Latest answer" })}
                  </h3>
                  <p>
                    {t({ zh: "参考分", en: "Reference score" })}{" "}
                    {attempt.overall ?? "—"}
                  </p>
                  <p className="whitespace-pre-wrap break-words">
                    {attempt.transcript ||
                      t({ zh: "暂无转写", en: "No transcript" })}
                  </p>
                  <AttemptAudio attemptId={attempt.id} className="w-full" />
                  {attempt.advice?.map((line) => (
                    <p className="break-words text-sm" key={line}>
                      {line}
                    </p>
                  ))}
                </article>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
