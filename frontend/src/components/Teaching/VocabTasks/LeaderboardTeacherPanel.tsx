import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ChevronLeft,
  ChevronRight,
  Eye,
  RotateCcw,
  Trophy,
  UsersRound,
} from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { VocabularyService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { EntryName } from "@/components/Vocabulary/Leaderboard/EntryName"
import { useI18n } from "@/lib/i18n"
import {
  canGoNextWeek,
  nextWeekStart,
  participantCountVisible,
  previousWeekStart,
} from "@/lib/leaderboard"
import { formatDate } from "@/lib/time"

type Audience = "teachers" | "students"

/**
 * 教师端「学习榜」面板（挂在 `/t/$code/vocab` 词汇 Tab）。
 *
 * - 只改榜单开关 / 可见范围 / 匿名口径；不提供任何改学生授权、等级或 XP 的操作。
 * - 预览表口径与学生端一致；教师可见参与人数，可回看历史周（上界为本周）。
 * - 保存后失效设置与榜单查询，预览随之刷新。
 */
export function LeaderboardTeacherPanel({ code }: { code: string }) {
  const { t, lang } = useI18n()
  const queryClient = useQueryClient()

  const settingsQuery = useQuery({
    queryKey: ["vocab", code, "leaderboard-settings"],
    queryFn: () =>
      VocabularyService.readLeaderboardSettings({ code: code.toUpperCase() }),
    retry: false,
  })

  const [weekStart, setWeekStart] = useState<string | null>(null)
  const [boundaryWeek, setBoundaryWeek] = useState<string | null>(null)
  const boardQuery = useQuery({
    queryKey: ["vocab", code, "leaderboard", "teacher", weekStart],
    queryFn: () =>
      VocabularyService.readLeaderboard({
        code: code.toUpperCase(),
        week_start: weekStart,
      }),
    retry: false,
  })

  // 表单本地状态：设置回包后回填；未取到时用后端默认口径
  const [enabled, setEnabled] = useState(true)
  const [audience, setAudience] = useState<Audience>("teachers")
  const [anonymous, setAnonymous] = useState(true)

  const settings = settingsQuery.data ?? null
  useEffect(() => {
    if (!settings) return
    setEnabled(settings.enabled)
    setAudience(settings.audience === "students" ? "students" : "teachers")
    setAnonymous(settings.anonymous)
  }, [settings])

  const view = boardQuery.data ?? null
  useEffect(() => {
    if (!view) return
    setBoundaryWeek((prev) => prev ?? view.week_start)
  }, [view])

  const saveMutation = useMutation({
    mutationFn: () =>
      VocabularyService.updateLeaderboardSettings({
        code: code.toUpperCase(),
        vocabularyLeaderboardSettingsUpdate: { enabled, audience, anonymous },
      }),
    onSuccess: () => {
      toast.success(t({ zh: "设置已保存。", en: "Settings saved." }))
      void queryClient.invalidateQueries({ queryKey: ["vocab", code] })
    },
    onError: () =>
      toast.error(
        t({
          zh: "保存失败，请稍后再试。",
          en: "Couldn't save settings. Please try again later.",
        }),
      ),
  })

  if (settingsQuery.isError) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 text-muted-foreground">
        <p>
          {t({
            zh: "学习榜设置暂时没有加载成功。",
            en: "The board settings failed to load.",
          })}
        </p>
        <Button
          variant="outline"
          onClick={() => void settingsQuery.refetch()}
          disabled={settingsQuery.isFetching}
        >
          <RotateCcw />
          {t({ zh: "重新加载", en: "Reload" })}
        </Button>
      </div>
    )
  }

  const entries = view?.entries ?? []
  const currentWeek = weekStart ?? view?.week_start ?? null
  const showCount = participantCountVisible(view?.participant_count)

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Trophy className="size-5" />
            {t({ zh: "学习榜设置", en: "Board settings" })}
          </CardTitle>
          <CardDescription>
            {t({
              zh: "按本周掌握词数排行；只读取作答记录，不改学生等级、授权或 XP。",
              en: "Ranked by words mastered this week. Answers are read-only; student levels, roles and XP are never changed.",
            })}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="flex items-center gap-2.5 text-sm">
            <Checkbox
              id="leaderboard-enabled"
              checked={enabled}
              onCheckedChange={(checked) => setEnabled(checked === true)}
            />
            <label htmlFor="leaderboard-enabled">
              {t({ zh: "在本班开启学习榜", en: "Enable the class board" })}
            </label>
          </div>

          <label className="flex flex-col gap-1.5 text-sm">
            <span className="text-xs text-muted-foreground">
              {t({ zh: "可见范围", en: "Who can see it" })}
            </span>
            <select
              value={audience}
              onChange={(event) => setAudience(event.target.value as Audience)}
              className="min-h-11 rounded-xl border bg-card px-3 text-base"
            >
              <option value="teachers">
                {t({ zh: "仅教师可见（默认）", en: "Teachers only (default)" })}
              </option>
              <option value="students">
                {t({ zh: "学生可见", en: "Students can see it" })}
              </option>
            </select>
          </label>

          <div className="flex items-center gap-2.5 text-sm sm:col-span-2">
            <Checkbox
              id="leaderboard-anonymous"
              checked={anonymous}
              onCheckedChange={(checked) => setAnonymous(checked === true)}
            />
            <label htmlFor="leaderboard-anonymous">
              {t({
                zh: "匿名编号（默认开）：关闭后榜单显示学生姓名",
                en: "Anonymous IDs (default on): turn off to show student names",
              })}
            </label>
          </div>

          <ul className="grid gap-2 rounded-2xl bg-secondary/50 p-4 text-xs leading-relaxed text-muted-foreground sm:col-span-2">
            <li>
              {t({
                zh: "默认仅教师可见、默认匿名；学生默认不参加。",
                en: "Default is teacher-only and anonymous; students do not join by default.",
              })}
            </li>
            <li>
              {t({
                zh: "未参加的学生看不到任何人，也看不到人数。",
                en: "Students who haven't joined see nobody and no headcount.",
              })}
            </li>
            <li>
              {t({
                zh: "切换为学生可见后，学生端才会出现加入入口。",
                en: "The join entry appears for students only after you switch to Students can see it.",
              })}
            </li>
          </ul>

          <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
            <Button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending || settingsQuery.isPending}
            >
              {saveMutation.isPending
                ? t({ zh: "保存中…", en: "Saving…" })
                : t({ zh: "保存设置", en: "Save settings" })}
            </Button>
            {settings?.audience === "students" && enabled && (
              <Badge variant="secondary">
                <Eye className="size-3" />
                {t({ zh: "学生可见中", en: "Visible to students" })}
              </Badge>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-wrap items-center justify-between gap-3 space-y-0">
          <div className="flex items-center gap-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <UsersRound className="size-5" />
              {t({ zh: "本周预览", en: "Weekly preview" })}
            </CardTitle>
            {showCount && (
              <Badge variant="outline">
                {t({
                  zh: `参与 ${view?.participant_count ?? 0} 人`,
                  en: `${view?.participant_count ?? 0} joined`,
                })}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              aria-label={t({ zh: "上一周", en: "Previous week" })}
              onClick={() =>
                currentWeek && setWeekStart(previousWeekStart(currentWeek))
              }
              disabled={boardQuery.isFetching}
            >
              <ChevronLeft />
            </Button>
            <span className="min-w-32 text-center text-sm tabular-nums text-muted-foreground">
              {currentWeek ? formatDate(currentWeek, lang) : "–"}
              {currentWeek !== null &&
                boundaryWeek !== null &&
                currentWeek === boundaryWeek && (
                  <span className="ml-2">
                    {t({ zh: "本周", en: "This week" })}
                  </span>
                )}
            </span>
            <Button
              variant="outline"
              size="sm"
              aria-label={t({ zh: "下一周", en: "Next week" })}
              onClick={() =>
                currentWeek && setWeekStart(nextWeekStart(currentWeek))
              }
              disabled={
                !currentWeek ||
                !canGoNextWeek(currentWeek, boundaryWeek) ||
                boardQuery.isFetching
              }
            >
              <ChevronRight />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {boardQuery.isError ? (
            <div className="flex flex-col items-center gap-3 py-8 text-sm text-muted-foreground">
              <p>
                {t({
                  zh: "预览暂时没有加载成功。",
                  en: "The preview failed to load.",
                })}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void boardQuery.refetch()}
                disabled={boardQuery.isFetching}
              >
                <RotateCcw />
                {t({ zh: "重新加载", en: "Reload" })}
              </Button>
            </div>
          ) : entries.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {t({
                zh: "本周还没有人完成复习。",
                en: "Nobody has completed a review this week yet.",
              })}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16 px-2 sm:w-20 sm:px-4">
                    {t({ zh: "名次", en: "Rank" })}
                  </TableHead>
                  <TableHead className="px-2 sm:px-4">
                    {t({ zh: "学生", en: "Student" })}
                  </TableHead>
                  <TableHead className="whitespace-normal px-2 text-right sm:px-4">
                    {t({ zh: "本周掌握词数", en: "Words mastered" })}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((entry) => (
                  <TableRow key={entry.alias_no}>
                    <TableCell className="px-2 tabular-nums text-muted-foreground sm:px-4">
                      {t({ zh: `第 ${entry.rank} 名`, en: `#${entry.rank}` })}
                    </TableCell>
                    <TableCell className="px-2 sm:px-4">
                      <EntryName
                        entry={entry}
                        anonymous={view?.settings.anonymous ?? true}
                      />
                    </TableCell>
                    <TableCell className="px-2 text-right font-semibold tabular-nums sm:px-4">
                      {entry.score}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
