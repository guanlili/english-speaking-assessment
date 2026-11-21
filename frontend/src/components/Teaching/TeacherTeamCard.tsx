import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Crown,
  Loader2,
  LogOut,
  Search,
  UserPlus,
  UsersRound,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { ClassesService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { cachedRole } from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"

function roleLabel(role: string, t: ReturnType<typeof useI18n>["t"]): string {
  if (role === "owner") return t({ zh: "主教师", en: "Lead teacher" })
  if (role === "school_admin") {
    return t({ zh: "校管理员", en: "School admin" })
  }
  return t({ zh: "共管教师", en: "Co-teacher" })
}

/**
 * 教师团队：主教师/共管教师/校管理员可读；主教师/校管理员可加/移除，
 * 共管教师只能退出自己。权限事实源在服务端 membership，前端仅做入口收敛。
 */
export function TeacherTeamCard({ code }: { code: string }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState("")
  const [addingId, setAddingId] = useState<string | null>(null)

  const teamQuery = useQuery({
    queryKey: ["class-teachers", code],
    queryFn: () => ClassesService.listClassTeachers({ code }),
  })
  const team = teamQuery.data ?? []
  const me = team.find((row) => row.is_me)
  const canManage = cachedRole() === "school_admin" || me?.role === "owner"

  const candidatesQuery = useQuery({
    queryKey: ["class-teacher-candidates", code, keyword],
    queryFn: () =>
      ClassesService.teacherCandidates({ code, q: keyword.trim() }),
    enabled: canManage && keyword.trim().length > 0,
    staleTime: 10_000,
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["class-teachers", code] })
    await queryClient.invalidateQueries({
      queryKey: ["class-teacher-candidates", code],
    })
    await queryClient.invalidateQueries({ queryKey: ["my-classrooms"] })
  }

  const addMutation = useMutation({
    mutationFn: (userId: string) =>
      ClassesService.addClassTeacher({
        code,
        classroomTeacherCreate: { user_id: userId },
      }),
    onSuccess: async (row) => {
      toast.success(
        t({
          zh: `已添加 ${row.full_name || "教师"} 为共管教师`,
          en: `Added ${row.full_name || "teacher"} as co-teacher`,
        }),
      )
      setAddingId(null)
      setKeyword("")
      await invalidate()
    },
    onError: (error) => {
      setAddingId(null)
      toast.error(extractErrorMessage(error))
    },
  })

  const removeMutation = useMutation({
    mutationFn: (userId: string) =>
      ClassesService.removeClassTeacher({ code, user_id: userId }),
    onSuccess: async (_data, userId) => {
      const leaving = userId === me?.user_id
      toast.success(
        leaving
          ? t({ zh: "已退出共管", en: "You left the teaching team" })
          : t({ zh: "已移除共管教师", en: "Co-teacher removed" }),
      )
      await invalidate()
      if (leaving) {
        window.location.href = "/classrooms"
      }
    },
    onError: (error) => toast.error(extractErrorMessage(error)),
  })

  const remove = (userId: string, name: string, isMe: boolean) => {
    const confirmed = window.confirm(
      isMe
        ? t({
            zh: "确认退出本班共管？退出后将失去课堂面板权限。",
            en: "Leave this teaching team? You will lose dashboard access.",
          })
        : t({
            zh: `确认移除 ${name} 的共管权限？`,
            en: `Remove ${name} from this teaching team?`,
          }),
    )
    if (confirmed) removeMutation.mutate(userId)
  }

  const candidates = candidatesQuery.data ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <UsersRound aria-hidden="true" className="size-4" />
          {t({ zh: "教师团队", en: "Teaching team" })}
        </CardTitle>
        <CardDescription>
          {t({
            zh: "主教师负责班级设置与团队管理；共管教师可查看名单、发布练习、批改与导出。",
            en: "The lead teacher controls class settings and the team. Co-teachers can view the roster, assign practice, give feedback and export.",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {teamQuery.isPending ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            {t({ zh: "正在加载教师团队…", en: "Loading teaching team…" })}
          </p>
        ) : teamQuery.isError ? (
          <p className="text-sm text-muted-foreground">
            {t({
              zh: "教师团队加载失败，请稍后重试。",
              en: "Failed to load the teaching team. Please retry.",
            })}
          </p>
        ) : (
          <ul className="space-y-2">
            {team.map((row) => (
              <li
                key={row.user_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-card px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                    <span className="break-all">
                      {row.full_name || row.email || row.user_id.slice(0, 8)}
                    </span>
                    {row.role === "owner" && (
                      <Crown
                        aria-label={t({ zh: "主教师", en: "Lead teacher" })}
                        className="size-3.5 text-amber-600"
                      />
                    )}
                    {row.is_me && (
                      <Badge variant="secondary">
                        {t({ zh: "我", en: "Me" })}
                      </Badge>
                    )}
                  </p>
                  {row.email && (
                    <p className="break-all text-xs text-muted-foreground">
                      {row.email}
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{roleLabel(row.role, t)}</Badge>
                  {row.role === "co_teacher" && (canManage || row.is_me) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="min-h-11 text-destructive"
                      disabled={removeMutation.isPending}
                      onClick={() =>
                        remove(
                          row.user_id,
                          row.full_name || "该教师",
                          row.is_me === true,
                        )
                      }
                    >
                      {row.is_me ? (
                        <LogOut />
                      ) : (
                        <UserPlus className="rotate-45" />
                      )}
                      {row.is_me
                        ? t({ zh: "退出共管", en: "Leave" })
                        : t({ zh: "移除", en: "Remove" })}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        {canManage && (
          <div className="space-y-2 border-t pt-3">
            <label
              htmlFor={`teacher-search-${code}`}
              className="text-sm font-medium"
            >
              {t({ zh: "添加共管教师", en: "Add a co-teacher" })}
            </label>
            <div className="relative">
              <Search className="pointer-events-none absolute top-3 left-3 size-4 text-muted-foreground" />
              <Input
                id={`teacher-search-${code}`}
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder={t({
                  zh: "输入本校教师姓名、邮箱或账号搜索",
                  en: "Search a school teacher by name, email or username",
                })}
                className="min-h-11 pl-9"
              />
            </div>
            {keyword.trim().length > 0 && (
              <div className="rounded-xl border bg-muted/20 p-2">
                {candidatesQuery.isPending ? (
                  <p className="flex items-center gap-2 px-1 py-1 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" />
                    {t({ zh: "搜索中…", en: "Searching…" })}
                  </p>
                ) : candidates.length === 0 ? (
                  <p className="px-1 py-1 text-sm text-muted-foreground">
                    {t({
                      zh: "没有可添加的本校教师（已在本班或账号停用）。",
                      en: "No available school teachers (already in this class or inactive).",
                    })}
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {candidates.map((candidate) => (
                      <li
                        key={candidate.id}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-lg px-2 py-1.5 hover:bg-background"
                      >
                        <div className="min-w-0">
                          <p className="break-all text-sm font-medium">
                            {candidate.full_name ||
                              candidate.username ||
                              "教师"}
                          </p>
                          {(candidate.email || candidate.username) && (
                            <p className="break-all text-xs text-muted-foreground">
                              {candidate.email || candidate.username}
                            </p>
                          )}
                        </div>
                        <Button
                          size="sm"
                          className="min-h-11"
                          disabled={addMutation.isPending}
                          onClick={() => {
                            setAddingId(candidate.id)
                            addMutation.mutate(candidate.id)
                          }}
                        >
                          {addMutation.isPending &&
                          addingId === candidate.id ? (
                            <Loader2 className="animate-spin" />
                          ) : (
                            <UserPlus />
                          )}
                          {t({ zh: "添加", en: "Add" })}
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default TeacherTeamCard
