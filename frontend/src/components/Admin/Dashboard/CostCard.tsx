import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { AdminService } from "@/client"
import InfoHint from "@/components/Common/InfoHint"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { EXPLAIN } from "@/lib/terms"

/** 费用区：本月估算卡 + 近 N 月趋势条 + 对账录入。估算口径见 EXPLAIN。 */
function CostCard() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const costQuery = useQuery({
    queryKey: ["admin", "dashboard", "cost"],
    queryFn: () => AdminService.readDashboardCost({ months: 6 }),
    staleTime: 5 * 60 * 1000,
  })

  const months = [...(costQuery.data?.months ?? [])].reverse()
  const current = months[0]
  const maxTotal = Math.max(...months.map((m) => m.total_cny), 1)

  const reconcileMutation = useMutation({
    mutationFn: (payload: { month: string; amount_cny: number }) =>
      AdminService.upsertCostReconcile({ requestBody: payload }),
    onSuccess: (_data, vars) => {
      showSuccessToast(
        t({
          zh: `${vars.month} 实际账单已记录`,
          en: `Actual bill for ${vars.month} saved`,
        }),
      )
      void queryClient.invalidateQueries({
        queryKey: ["admin", "dashboard", "cost"],
      })
    },
    onError: () => {
      showErrorToast(t({ zh: "保存失败", en: "Save failed" }))
    },
  })

  const latest = current?.month ?? ""
  const [amount, setAmount] = useState("")
  const targetMonth = latest
  const actual = current?.actual_cny

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          {t({ zh: "费用估算", en: "Cost estimate" })}
          <InfoHint label={t(EXPLAIN.dashboard_cost)} />
        </CardTitle>
        <CardDescription>
          {costQuery.data?.note ??
            t({
              zh: "按月估算；实际以云账单为准。",
              en: "Monthly estimates; actual costs follow cloud bills.",
            })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {costQuery.isPending ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t({ zh: "正在加载…", en: "Loading…" })}
          </p>
        ) : months.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t({ zh: "暂无数据。", en: "No data yet." })}
          </p>
        ) : (
          <>
            {/* 本月速览 */}
            {current ? (
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <div className="rounded-xl border p-3">
                  <p className="text-xs text-muted-foreground">
                    {t({ zh: "语音识别", en: "ASR" })}
                  </p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">
                    ¥{current.asr_cny.toFixed(2)}
                  </p>
                  <p className="text-xs text-muted-foreground tabular-nums">
                    {(current.asr_seconds / 3600).toFixed(2)}{" "}
                    {t({ zh: "小时", en: "h" })}
                  </p>
                </div>
                <div className="rounded-xl border p-3">
                  <p className="text-xs text-muted-foreground">
                    {t({ zh: "语言模型", en: "LLM" })}
                  </p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">
                    ¥{current.llm_cny.toFixed(2)}
                  </p>
                  <p className="text-xs text-muted-foreground tabular-nums">
                    {current.llm_calls} {t({ zh: "次调用", en: "calls" })}
                  </p>
                </div>
                <div className="rounded-xl border p-3">
                  <p className="text-xs text-muted-foreground">
                    {t({ zh: "服务器", en: "Server" })}
                  </p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">
                    ¥{current.server_cny.toFixed(2)}
                  </p>
                </div>
                <div className="rounded-xl border p-3">
                  <p className="text-xs text-muted-foreground">
                    {t({ zh: "合计（估算）", en: "Total (est.)" })}
                  </p>
                  <p className="mt-1 text-lg font-bold tabular-nums">
                    ¥{current.total_cny.toFixed(2)}
                  </p>
                  {current.attempts > 0 ? (
                    <p className="text-xs text-muted-foreground tabular-nums">
                      ¥{(current.total_cny / current.attempts).toFixed(3)}/
                      {t({ zh: "作答", en: "attempt" })}
                    </p>
                  ) : null}
                </div>
              </div>
            ) : null}

            {/* 月度趋势条 */}
            <div className="space-y-1.5">
              {months.map((m) => (
                <div key={m.month} className="flex items-center gap-2">
                  <span className="w-16 shrink-0 text-xs tabular-nums text-muted-foreground">
                    {m.month}
                  </span>
                  <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary/80"
                      style={{ width: `${(m.total_cny / maxTotal) * 100}%` }}
                    />
                  </div>
                  <span className="w-20 shrink-0 text-right text-xs tabular-nums">
                    ¥{m.total_cny.toFixed(2)}
                  </span>
                  <span className="w-24 shrink-0 text-right text-xs tabular-nums">
                    {m.actual_cny != null ? (
                      <span
                        className={
                          (m.deviation_pct ?? 0) > 20 ||
                          (m.deviation_pct ?? 0) < -20
                            ? "text-amber-600"
                            : "text-muted-foreground"
                        }
                      >
                        {t({ zh: "实际", en: "actual" })} ¥
                        {m.actual_cny.toFixed(0)}
                      </span>
                    ) : (
                      <span className="text-muted-foreground/60">—</span>
                    )}
                  </span>
                </div>
              ))}
            </div>

            {/* 对账录入 */}
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed p-3">
              <span className="text-sm text-muted-foreground">
                {t({
                  zh: `${targetMonth} 实际账单`,
                  en: `Actual bill ${targetMonth}`,
                })}
                ：
              </span>
              <Input
                type="number"
                min="0"
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder={actual != null ? actual.toFixed(2) : "¥"}
                className="w-28 text-base"
                aria-label={t({ zh: "实际账单金额", en: "Actual bill amount" })}
              />
              <Button
                variant="outline"
                size="sm"
                className="min-h-11"
                disabled={
                  !targetMonth || !amount || reconcileMutation.isPending
                }
                onClick={() => {
                  const n = Number(amount)
                  if (Number.isFinite(n) && n > 0 && targetMonth) {
                    reconcileMutation.mutate({
                      month: targetMonth,
                      amount_cny: n,
                    })
                    setAmount("")
                  }
                }}
              >
                {t({ zh: "保存", en: "Save" })}
              </Button>
              {current?.deviation_pct != null ? (
                <span className="text-xs text-muted-foreground tabular-nums">
                  {t({ zh: "偏差", en: "deviation" })}{" "}
                  {current.deviation_pct > 0 ? "+" : ""}
                  {current.deviation_pct}%
                </span>
              ) : null}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

export default CostCard
