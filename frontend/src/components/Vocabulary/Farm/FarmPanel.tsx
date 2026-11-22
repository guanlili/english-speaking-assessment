import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { VocabularyService } from "@/client"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

import FarmPlotView from "./FarmPlotView"

/**
 * 专注农场面板：拉取地块快照，驱动收获入账。
 *
 * 边界（设计稿 §4）：班内自愿参与、不跨校公开；农场奖励不替代教师任务的
 * 首答统计与快照口径；XP / streak / 徽章一律读既有课堂账本。
 */
export default function FarmPanel({ code }: { code: string }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const farmQuery = useQuery({
    queryKey: ["vocab", code, "farm"],
    queryFn: () => VocabularyService.readFarm({ code: code.toUpperCase() }),
    staleTime: 5_000,
  })

  const harvest = useMutation({
    mutationFn: () =>
      VocabularyService.harvestFarm({ code: code.toUpperCase() }),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({
        queryKey: ["vocab", code, "farm"],
      })
      toast.success(
        t({
          zh: `收获成功，+${data.xp_gained ?? 10} XP`,
          en: `Harvested · +${data.xp_gained ?? 10} XP`,
        }),
      )
    },
    onError: () => {
      toast.error(
        t({
          zh: "暂时不能收获：作物未成熟或今日农场 XP 已达上限。",
          en: "Can't harvest yet: not mature, or today's farm XP limit reached.",
        }),
      )
    },
  })

  if (farmQuery.isPending) {
    return (
      <p
        role="status"
        className="py-10 text-center text-sm text-muted-foreground"
      >
        {t({ zh: "正在加载农场…", en: "Loading your farm…" })}
      </p>
    )
  }

  if (farmQuery.isError || !farmQuery.data) {
    return (
      <div role="alert" className="grid gap-3 py-10 text-center">
        <p className="text-sm text-muted-foreground">
          {t({
            zh: "农场暂时没有加载出来，请稍后重试。",
            en: "Your farm failed to load — please try again later.",
          })}
        </p>
        <Button variant="outline" onClick={() => void farmQuery.refetch()}>
          {t({ zh: "重新加载", en: "Reload" })}
        </Button>
      </div>
    )
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">
            {t({ zh: "专注农场", en: "Focus Farm" })}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t({
              zh: "本班自愿参与；农场奖励独立于教师任务成绩，不做公开排行。",
              en: "Optional in-class activity. Farm rewards stay separate from teacher tasks — no public leaderboard.",
            })}
          </p>
        </div>
      </div>
      <FarmPlotView
        view={farmQuery.data}
        harvesting={harvest.isPending}
        onHarvest={() => harvest.mutate()}
      />
    </div>
  )
}
