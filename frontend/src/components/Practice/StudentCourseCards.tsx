import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ArrowRight, BookA, Mic } from "lucide-react"
import type { ReactNode } from "react"

import { VocabularyService } from "@/client"
import { useModules } from "@/hooks/useModules"
import { COURSES } from "@/lib/courses"
import { useI18n } from "@/lib/i18n"

interface CourseCard {
  key: string
  icon: ReactNode
  name: string
  tagline: string
  status: string
  action: string
  to: "/p/$code" | "/vocab/$code"
}

/**
 * 学生端「我的课程」卡片区（英语学习中心 P1）。
 *
 * 平台不是口语产品：口语课、单词课并列展示，各自说明"今天该做什么"。
 * 未开通的课程整卡不出现（不是置灰占位）；两门课各取各的接口，一门课取数
 * 失败只影响自己这张卡（降级为"暂时不可用"），不拖垮整页。
 */
export function StudentCourseCards({
  code,
  speakingDone,
  speakingTotal,
}: {
  code: string
  speakingDone: number
  speakingTotal: number
}) {
  const { t } = useI18n()
  const { hasModule, isPending } = useModules()

  const speakingEnabled = hasModule("speaking")
  const vocabEnabled = hasModule("vocabulary")

  const vocabQuery = useQuery({
    retry: 1,
    queryKey: ["vocabulary", code, "today"],
    queryFn: () =>
      VocabularyService.readVocabToday({ code: code.toUpperCase() }),
    enabled: vocabEnabled,
  })

  const speakingStatus =
    speakingTotal > 0
      ? speakingDone >= speakingTotal
        ? t({ zh: "今日练习已完成", en: "Today's practice is done" })
        : t({
            zh: `今日练习 ${speakingDone} / ${speakingTotal}`,
            en: `Today's practice ${speakingDone} / ${speakingTotal}`,
          })
      : t({ zh: "等待老师安排内容", en: "Waiting for your teacher" })

  const vocabAssignment = vocabQuery.data?.assignment ?? null
  const vocabStatus = vocabQuery.isPending
    ? t({ zh: "正在加载…", en: "Loading…" })
    : vocabQuery.isError
      ? t({ zh: "暂时不可用", en: "Temporarily unavailable" })
      : vocabAssignment
        ? t({
            zh: `今日任务 ${vocabAssignment.word_count} 词`,
            en: `Today's task: ${vocabAssignment.word_count} words`,
          })
        : t({
            zh: "今日无任务，可自主练习",
            en: "No task today — free practice",
          })

  const cards: Array<CourseCard | null> = [
    speakingEnabled
      ? {
          key: "speaking",
          icon: <Mic className="size-4" aria-hidden="true" />,
          name: t(COURSES.speaking.name),
          tagline: t(COURSES.speaking.tagline),
          status: speakingStatus,
          action: t({ zh: "去练口语", en: "Practise speaking" }),
          to: "/p/$code",
        }
      : null,
    vocabEnabled
      ? {
          key: "vocabulary",
          icon: <BookA className="size-4" aria-hidden="true" />,
          name: t(COURSES.vocabulary.name),
          tagline: t(COURSES.vocabulary.tagline),
          status: vocabStatus,
          action: t({ zh: "去背单词", en: "Study words" }),
          to: "/vocab/$code",
        }
      : null,
  ]
  const visibleCards = cards.filter((card): card is CourseCard => card !== null)

  if (isPending || visibleCards.length === 0) return null

  return (
    <section aria-labelledby="my-courses-heading" className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 id="my-courses-heading" className="text-sm font-semibold">
          {t({ zh: "我的课程", en: "My Courses" })}
        </h2>
        <span className="text-[11px] text-muted-foreground">
          {t({
            zh: "同一节课，两种练法",
            en: "One class, two ways to practise",
          })}
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {visibleCards.map((card) => (
          <Link
            key={card.key}
            to={card.to}
            params={{ code }}
            className="group flex min-h-24 flex-col gap-2 rounded-2xl border border-border/70 bg-card px-4 py-4 transition-colors hover:border-primary/40 hover:bg-secondary/40"
          >
            <div className="flex items-center gap-2 text-sm font-semibold">
              <span className="grid size-7 place-items-center rounded-full bg-secondary text-primary">
                {card.icon}
              </span>
              {card.name}
              <ArrowRight className="ml-auto size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </div>
            <p className="text-[11px] leading-5 text-muted-foreground">
              {card.tagline}
            </p>
            <div className="mt-auto flex items-center justify-between gap-2">
              <span className="text-xs font-medium">{card.status}</span>
              <span className="text-[11px] text-primary">{card.action}</span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  )
}
