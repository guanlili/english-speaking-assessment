import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { LayoutDashboard } from "lucide-react"
import { useState } from "react"
import { AdminService } from "@/client"
import ClassroomRankCard from "@/components/Admin/Dashboard/ClassroomRankCard"
import ContentAssetsCard from "@/components/Admin/Dashboard/ContentAssetsCard"
import OverviewCards from "@/components/Admin/Dashboard/OverviewCards"
import {
  ItemDistributionCard,
  UsageTrendCard,
} from "@/components/Admin/Dashboard/UsageTrendCard"
import { Card, CardContent } from "@/components/ui/card"
import { APP_NAME } from "@/config"
import { useI18n } from "@/lib/i18n"

/** 时间档位：值即后端 days 参数；「全部」用大窗口近似。 */
const RANGES = [
  { days: 7, zh: "近 7 天", en: "7 days" },
  { days: 30, zh: "近 30 天", en: "30 days" },
  { days: 90, zh: "近 90 天", en: "90 days" },
  { days: 3650, zh: "全部", en: "All" },
]

function AdminDashboardPage() {
  const { t } = useI18n()
  const [days, setDays] = useState(30)

  const overviewQuery = useQuery({
    queryKey: ["admin", "dashboard", "overview", days],
    queryFn: () => AdminService.readDashboardOverview({ days }),
  })
  const usageQuery = useQuery({
    queryKey: ["admin", "dashboard", "usage", days],
    queryFn: () => AdminService.readDashboardUsage({ days }),
  })
  const contentQuery = useQuery({
    queryKey: ["admin", "dashboard", "content"],
    queryFn: () => AdminService.readDashboardContent(),
    staleTime: 5 * 60 * 1000,
  })

  const rangeLabel =
    days === 3650
      ? t({ zh: "全部", en: "All time" })
      : t({ zh: `近 ${days} 天`, en: `Last ${days} days` })

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 p-4 md:p-6">
      <header className="space-y-1">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <LayoutDashboard className="size-6 text-primary" aria-hidden="true" />
          {t({ zh: "平台大盘", en: "Platform Dashboard" })}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t({
            zh: "全平台使用情况一页总览：使用量、分数走势、课堂排行与资产存量。",
            en: "Platform-wide usage at a glance: volume, score trends, classroom ranking, and content totals.",
          })}
        </p>
      </header>

      <Card className="py-3">
        <CardContent className="flex flex-wrap items-center gap-2 px-4">
          <span className="text-sm text-muted-foreground">
            {t({ zh: "时间范围", en: "Range" })}
          </span>
          <div
            role="tablist"
            aria-label={t({ zh: "时间范围", en: "Range" })}
            className="flex flex-wrap gap-1"
          >
            {RANGES.map((r) => (
              <button
                key={r.days}
                type="button"
                role="tab"
                aria-selected={days === r.days}
                onClick={() => setDays(r.days)}
                className={
                  "min-h-11 rounded-lg px-3 text-sm transition-colors " +
                  (days === r.days
                    ? "bg-primary font-medium text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground")
                }
              >
                {t(r)}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <OverviewCards
        overview={overviewQuery.data}
        pending={overviewQuery.isPending}
        rangeLabel={rangeLabel}
      />

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <UsageTrendCard points={usageQuery.data?.points ?? []} />
        </div>
        <ItemDistributionCard
          distribution={usageQuery.data?.item_distribution ?? {}}
        />
      </div>

      <ClassroomRankCard
        classrooms={usageQuery.data?.classrooms}
        silent={usageQuery.data?.silent_classrooms}
        pending={usageQuery.isPending}
      />

      <ContentAssetsCard
        content={contentQuery.data}
        pending={contentQuery.isPending}
      />
    </div>
  )
}

export const Route = createFileRoute("/_layout/admin/dashboard")({
  component: AdminDashboardPage,
  head: () => ({
    meta: [{ title: `平台大盘 / Dashboard - ${APP_NAME}` }],
  }),
})
