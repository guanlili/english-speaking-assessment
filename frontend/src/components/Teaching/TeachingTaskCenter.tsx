import { useQueries, useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ArrowRight, BookA, Mic } from "lucide-react"
import type { ReactNode } from "react"
import type {
  BoardData,
  ClassroomPublic,
  VocabularyTeacherAssignmentRow,
} from "@/client"
import { ClassesService, VocabularyService } from "@/client"
import { TeachingPageHeader } from "@/components/Teaching/TeachingPageHeader"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useModules } from "@/hooks/useModules"
import { COURSES } from "@/lib/courses"
import { useI18n } from "@/lib/i18n"

/**
 * 教师端「教学任务中心」：一个班、多门课，跨课程看今天该盯什么。
 *
 * 口径：
 * - 班级是共享底座（一门课建一个班会分裂名单），因此按班级聚合，列按课程拆；
 * - 口语课进度取课堂面板的 completed_count / 名单数；单词课取最近一条
 *   published 任务的目标-完成人数；
 * - 单班某门课取数失败只让该格降级为「—」，不影响整页（课程服务相互独立）。
 */
export function TeachingTaskCenter() {
  const { t } = useI18n()
  const { hasModule } = useModules()

  const classesQuery = useQuery({
    queryKey: ["my-classrooms"],
    queryFn: () => ClassesService.listMyClassrooms(),
  })

  const classrooms: ClassroomPublic[] = classesQuery.data ?? []
  const speakingEnabled = hasModule("speaking")
  const vocabEnabled = hasModule("vocabulary")

  const boardQueries = useQueries({
    queries: classrooms.map((classroom) => ({
      queryKey: ["task-center", "board", classroom.code],
      queryFn: () => ClassesService.readClassBoard({ code: classroom.code }),
      enabled: speakingEnabled,
      retry: false,
    })),
  })

  const vocabQueries = useQueries({
    queries: classrooms.map((classroom) => ({
      queryKey: ["task-center", "vocab", classroom.code],
      queryFn: () =>
        VocabularyService.listAssignments({ code: classroom.code }),
      enabled: vocabEnabled,
      retry: false,
    })),
  })

  if (classesQuery.isPending) {
    return (
      <div role="status" className="space-y-4">
        <span className="sr-only">
          {t({ zh: "正在加载教学任务…", en: "Loading teaching tasks…" })}
        </span>
        <Skeleton className="h-32 rounded-2xl" />
        <Skeleton className="h-32 rounded-2xl" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <TeachingPageHeader
        eyebrow={t({ zh: "教学工作台", en: "Teaching workspace" })}
        title={t({ zh: "教学任务中心", en: "Teaching Tasks" })}
        description={t({
          zh: "一个班、多门课：口语课和单词课今天各自进展到哪一步。",
          en: "One class, several courses: where speaking and vocabulary stand today.",
        })}
      />

      {classrooms.length === 0 ? (
        <Card className="px-6 py-12 text-center text-sm text-muted-foreground">
          {t({
            zh: "还没有课堂，先建一个班级。",
            en: "No classes yet — create one first.",
          })}
          <div className="mt-4">
            <Button asChild>
              <Link to="/classrooms">
                {t({ zh: "去我的课堂", en: "Go to My Classrooms" })}
              </Link>
            </Button>
          </div>
        </Card>
      ) : (
        <div className="space-y-3">
          {classrooms.map((classroom, index) => (
            <ClassTaskRow
              key={classroom.code}
              classroom={classroom}
              board={boardQueries[index]?.data ?? null}
              boardFailed={boardQueries[index]?.isError ?? false}
              speakingEnabled={speakingEnabled}
              vocabEnabled={vocabEnabled}
              vocabRows={vocabQueries[index]?.data ?? null}
              vocabFailed={vocabQueries[index]?.isError ?? false}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ClassTaskRow({
  classroom,
  board,
  boardFailed,
  speakingEnabled,
  vocabEnabled,
  vocabRows,
  vocabFailed,
}: {
  classroom: ClassroomPublic
  board: BoardData | null
  boardFailed: boolean
  speakingEnabled: boolean
  vocabEnabled: boolean
  vocabRows: VocabularyTeacherAssignmentRow[] | null
  vocabFailed: boolean
}) {
  const { t } = useI18n()

  const rosterCount = board?.students.length ?? classroom.class_size
  const speakingAssigned = board?.assignment ?? null
  const speakingDone = board?.completed_count ?? 0

  const activeAssignments =
    vocabRows?.filter((row) => row.assignment.status === "published") ?? []
  const latest = activeAssignments[0] ?? null

  return (
    <Card className="flex flex-col gap-4 p-4 sm:p-5 lg:flex-row lg:items-center">
      <div className="min-w-0 lg:w-56">
        <div className="flex items-center gap-2">
          <h3 className="truncate text-sm font-semibold">{classroom.name}</h3>
          <Badge variant="outline" className="shrink-0">
            {classroom.code}
          </Badge>
        </div>
        <p className="mt-1 text-[11px] text-muted-foreground">
          {t({ zh: `${rosterCount} 名学生`, en: `${rosterCount} students` })}
          {classroom.grade ? ` · ${classroom.grade}` : ""}
        </p>
      </div>

      <div className="grid flex-1 gap-3 sm:grid-cols-2">
        {speakingEnabled && (
          <CourseCell
            icon={<Mic className="size-3.5" aria-hidden="true" />}
            course={t(COURSES.speaking.name)}
            title={
              boardFailed
                ? t({ zh: "—", en: "—" })
                : (speakingAssigned?.title ??
                  t({
                    zh: "今天还没有发布练习",
                    en: "Nothing published today",
                  }))
            }
            meta={
              speakingAssigned && !boardFailed
                ? t({
                    zh: `已完成 ${speakingDone} / ${rosterCount}`,
                    en: `${speakingDone} / ${rosterCount} done`,
                  })
                : null
            }
            to="/t/$code"
            code={classroom.code}
            action={t({ zh: "口语工作台", en: "Speaking desk" })}
          />
        )}

        {vocabEnabled && (
          <CourseCell
            icon={<BookA className="size-3.5" aria-hidden="true" />}
            course={t(COURSES.vocabulary.name)}
            title={
              vocabFailed
                ? t({ zh: "—", en: "—" })
                : (latest?.assignment.title ??
                  t({ zh: "没有进行中的任务", en: "No active assignment" }))
            }
            meta={
              latest && !vocabFailed
                ? t({
                    zh: `${activeAssignments.length} 个任务进行中 · 最新 ${latest.completed_count ?? 0} / ${latest.target_count ?? 0}`,
                    en: `${activeAssignments.length} active · latest ${latest.completed_count ?? 0} / ${latest.target_count ?? 0}`,
                  })
                : null
            }
            to="/t/$code/vocab"
            code={classroom.code}
            action={t({ zh: "单词工作台", en: "Vocabulary desk" })}
          />
        )}
      </div>

      {!speakingEnabled && !vocabEnabled && (
        <p className="text-xs text-muted-foreground">
          {t({
            zh: "本校尚未开通课程，请联系学校管理员。",
            en: "No course is enabled yet — contact your school admin.",
          })}
        </p>
      )}
    </Card>
  )
}

function CourseCell({
  icon,
  course,
  title,
  meta,
  to,
  code,
  action,
}: {
  icon: ReactNode
  course: string
  title: string
  meta: string | null
  to: "/t/$code" | "/t/$code/vocab"
  code: string
  action: string
}) {
  return (
    <Link
      to={to}
      params={{ code }}
      className="group flex flex-col gap-1 rounded-xl border border-border/60 bg-secondary/30 px-3 py-2.5 transition-colors hover:border-primary/40 hover:bg-secondary/60"
    >
      <span className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
        {icon}
        {course}
      </span>
      <span className="line-clamp-1 text-sm font-medium">{title}</span>
      <span className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted-foreground">{meta ?? ""}</span>
        <span className="flex items-center gap-0.5 shrink-0 text-[11px] text-primary">
          {action}
          <ArrowRight className="size-3 transition-transform group-hover:translate-x-0.5" />
        </span>
      </span>
    </Link>
  )
}
