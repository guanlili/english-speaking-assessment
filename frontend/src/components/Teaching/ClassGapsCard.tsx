import { useQuery } from "@tanstack/react-query"
import { ClassesService } from "@/client"
import { useI18n } from "@/lib/i18n"
import { ITEM_TYPE_LABELS } from "@/lib/terms"

/** 今日当前发布：共同漏词和均分偏低的题。单独请求，不进名单轮询。 */
export function ClassGapsCard({
  code,
  refreshMs,
}: {
  code: string
  refreshMs: number
}) {
  const { t } = useI18n()
  const query = useQuery({
    queryKey: ["teacher", "weak-spots", code],
    queryFn: () =>
      ClassesService.readClassWeakSpots({ code: code.toUpperCase() }),
    refetchInterval: refreshMs,
  })
  const gaps = query.data

  return (
    <section className="space-y-3 rounded-2xl border border-border/80 bg-card p-5">
      <div className="space-y-1">
        <h2 className="text-base font-semibold">
          {t({ zh: "这节课全班卡在", en: "Where the class got stuck" })}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t({
            zh: "根据今日当前发布里已出分的朗读和复述转写，对照参考文本统计漏掉的内容词。这不是发音评分。",
            en: "Content words missed in today's scored reading and repeat transcripts, compared with the reference text. This is not a pronunciation score.",
          })}
        </p>
      </div>
      {query.isPending ? (
        <p role="status" className="text-sm text-muted-foreground">
          {t({ zh: "正在汇总…", en: "Gathering…" })}
        </p>
      ) : query.isError ? (
        <p role="alert" className="text-sm text-muted-foreground">
          {t({
            zh: "薄弱点暂时没有加载成功。",
            en: "Couldn't load the class gaps.",
          })}
        </p>
      ) : gaps && (gaps.word_gaps.length > 0 || gaps.low_items.length > 0) ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <h3 className="text-sm font-medium">
              {t({ zh: "多人漏掉的词", en: "Words several students missed" })}
            </h3>
            {gaps.word_gaps.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t({
                  zh: "还没有共同漏词。",
                  en: "No shared missing words yet.",
                })}
              </p>
            ) : (
              <ul className="space-y-1 text-sm">
                {gaps.word_gaps.map((gap) => (
                  <li key={gap.word} className="flex justify-between gap-3">
                    <span className="font-medium">{gap.word}</span>
                    <span className="text-muted-foreground">
                      {t({
                        zh: `${gap.student_count} 人`,
                        en: `${gap.student_count} students`,
                      })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="space-y-2">
            <h3 className="text-sm font-medium">
              {t({ zh: "均分偏低的题", en: "Lower-scoring items" })}
            </h3>
            {gaps.low_items.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t({
                  zh: "还没有明显偏低的题目。",
                  en: "No clearly low items yet.",
                })}
              </p>
            ) : (
              <ul className="space-y-2 text-sm">
                {gaps.low_items.map((item) => (
                  <li key={item.item_id} className="space-y-0.5">
                    <p className="font-medium">
                      {t(
                        ITEM_TYPE_LABELS[item.item_type] ?? {
                          zh: item.item_type,
                          en: item.item_type,
                        },
                      )}
                      {" · "}
                      {item.label}
                    </p>
                    <p className="text-muted-foreground">
                      {t({
                        zh: `均分 ${item.avg_overall} · ${item.low_count}/${item.scored_count} 人低于 70`,
                        en: `Avg ${item.avg_overall} · ${item.low_count}/${item.scored_count} below 70`,
                      })}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {t({
            zh: "还没有足够的已出分作答，交卷后这里会列出共同漏词。",
            en: "Not enough scored answers yet. Shared missing words show up after students submit.",
          })}
        </p>
      )}
    </section>
  )
}
