import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Archive } from "lucide-react"
import { AdminService } from "@/client"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { APP_NAME } from "@/config"
import { useI18n } from "@/lib/i18n"

export const Route = createFileRoute("/_layout/admin/wordlist")({
  component: WordlistAdmin,
  head: () => ({
    meta: [{ title: `老词表（已退役）/ Graded Word List - ${APP_NAME}` }],
  }),
})

/**
 * 老词表（A2/B1/B2）只读页（2026-10 下线导入）。
 *
 * 全系统现行为五级词库口径（/admin/vocablevels）；本页仅保留历史词表的
 * 只读统计——历史 attempt 中的 A2/B1/B2 词汇分析仍按老口径展示（不回填
 * 不重算）。CSV 导入端点已返回 410。
 */
function WordlistAdmin() {
  const { t } = useI18n()
  const statsQuery = useQuery({
    queryKey: ["admin", "wordlist"],
    queryFn: () => AdminService.wordlistStats(),
  })

  const stats = statsQuery.data
  const bands = Object.entries(stats?.by_band ?? {})

  return (
    <div className="space-y-6">
      <Card className="border-amber-500/30 bg-amber-500/5">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Archive className="size-4 text-amber-600" />
            {t({
              zh: "老词表（A2/B1/B2）已退役",
              en: "Old wordlist (A2/B1/B2) retired",
            })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "全系统现行为五级词库口径（KET/PET/学术/CET-4/雅思托福，见「五级词库」页）。本页只读保留历史词表统计：历史口语作答中的 A2/B1/B2 词汇分析原样展示，不回填不重算；CSV 导入已下线。",
              en: "The five-level word source (KET/PET/Academic/CET-4/IELTS & TOEFL, see the Leveled page) is now the system-wide standard. This page keeps read-only stats for the historical wordlist: A2/B1/B2 analysis in past attempts is preserved as-is (no backfill, no recompute). CSV import has been removed.",
            })}
          </CardDescription>
        </CardHeader>
      </Card>

      {statsQuery.isPending ? (
        <div role="status" className="space-y-3">
          <span className="sr-only">
            {t({ zh: "正在加载词表统计…", en: "Loading wordlist stats…" })}
          </span>
          <Skeleton className="h-24 rounded-2xl" />
        </div>
      ) : statsQuery.isError ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            {t({
              zh: "统计加载失败，请刷新重试。",
              en: "Failed to load stats — refresh to retry.",
            })}
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardContent className="py-4">
              <p className="text-xs text-muted-foreground">
                {t({ zh: "历史词表词条数", en: "Historical entries" })}
              </p>
              <p className="mt-1 text-3xl font-bold tabular-nums">
                {stats?.total ?? 0}
              </p>
              {(stats?.name ?? "") && (
                <p className="mt-1 text-xs text-muted-foreground">
                  {stats?.name}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">
                {t({ zh: "按档分布", en: "By band" })}
              </CardTitle>
            </CardHeader>
            <CardContent className="pb-2">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t({ zh: "档位", en: "Band" })}</TableHead>
                    <TableHead>{t({ zh: "词条数", en: "Entries" })}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {bands.map(([band, count]) => (
                    <TableRow key={band}>
                      <TableCell>
                        <Badge variant="outline">{band}</Badge>
                      </TableCell>
                      <TableCell className="tabular-nums">{count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
