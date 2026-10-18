import { useState } from "react"
import { Button } from "@/components/ui/button"
import { usePublishedClassSummaries } from "@/hooks/useClassroomMessages"
import { useI18n } from "@/lib/i18n"
import { formatDateTime } from "@/lib/time"
export function PublishedClassSummaries({ code }: { code: string }) {
  const { t, lang } = useI18n()
  const [offset, setOffset] = useState(0)
  const query = usePublishedClassSummaries(code, offset)
  if (query.isSuccess && offset === 0 && query.data.length === 0) return null
  return (
    <section
      aria-label={t({
        zh: "老师的课堂小结",
        en: "Class summaries from your teacher",
      })}
      className="space-y-3 rounded-2xl border bg-card p-5"
    >
      <h2 className="font-semibold">
        {t({ zh: "老师的课堂小结", en: "Class summaries from your teacher" })}
      </h2>
      {query.isPending ? (
        <p role="status">{t({ zh: "正在加载…", en: "Loading…" })}</p>
      ) : query.isError ? (
        <Button
          variant="outline"
          className="min-h-11"
          onClick={() => void query.refetch()}
        >
          {t({ zh: "小结加载失败，重试", en: "Summaries unavailable. Retry" })}
        </Button>
      ) : !query.data?.length ? (
        <p className="text-sm text-muted-foreground">
          {t({
            zh: "老师尚未发布课堂小结。",
            en: "Your teacher has not published a class summary yet.",
          })}
        </p>
      ) : (
        query.data.slice(0, 10).map((row) => (
          <details key={row.exercise_id} className="rounded-xl border p-3">
            <summary className="min-h-11 cursor-pointer break-words py-2 font-medium">
              {row.title}
            </summary>
            <p className="mb-2 text-xs text-muted-foreground">
              {formatDateTime(row.published_at, lang)}
            </p>
            <p className="whitespace-pre-wrap break-words text-sm">
              {row.text}
            </p>
          </details>
        ))
      )}
      <div className="flex flex-wrap gap-2">
        {offset > 0 && (
          <Button
            variant="outline"
            className="min-h-11"
            onClick={() => setOffset((value) => Math.max(0, value - 10))}
          >
            {t({ zh: "更新的小结", en: "Newer summaries" })}
          </Button>
        )}
        {(query.data?.length ?? 0) > 10 && (
          <Button
            variant="outline"
            className="min-h-11"
            onClick={() => setOffset((value) => value + 10)}
          >
            {t({ zh: "更早的小结", en: "Older summaries" })}
          </Button>
        )}
      </div>
    </section>
  )
}
