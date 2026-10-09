import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { toast } from "sonner"
import type { PlanItem } from "@/client"
import { ClassesService } from "@/client"
import { useI18n } from "@/lib/i18n"

/**
 * 「换一题」（US-06）：同主题同档换一道没做过的题；探索轮绑定 session_id。
 * 换来的题经 onExtraQuestion 回传给页面，以本地 PlanItem 追加（完成后随
 * attempts 展示；刷新后由后端从 attempt.item_snapshot 恢复）。
 * ?next=1（结果页「换同主题下一问」跳转过来）时自动执行一次，闩锁保证只触发一次。
 */
export function useNextQuestion({
  code,
  sessionId,
  items,
  todayQueryKey,
  nextFlag,
  studentReady,
  planLoaded,
  planError,
  hasExam,
  onExtraQuestion,
}: {
  code: string
  sessionId: string | undefined
  items: PlanItem[]
  todayQueryKey: readonly unknown[]
  nextFlag: boolean
  /** 学生本地身份已就绪（student !== null） */
  studentReady: boolean
  /** 今日计划加载成功（todayQuery.isSuccess） */
  planLoaded: boolean
  /** 今日计划加载失败（todayQuery.isError） */
  planError: boolean
  /** 模考中不换题（todayQuery.data?.exam 非空） */
  hasExam: boolean
  /** 换来的题回传页面（本地追加到题单） */
  onExtraQuestion: (item: PlanItem) => void
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const nextQuestionMutation = useMutation({
    mutationFn: () =>
      ClassesService.readNextQuestion({
        code: code.toUpperCase(),
        ...(sessionId ? { sessionId } : {}),
        ...(items.length ? { excludeIds: items.map((i) => i.id) } : {}),
      }),
    onSuccess: (data) => {
      if (data.question) {
        // 显式契约转换：ScenarioQuestionPublic → PlanItem(type="question")，
        // 不使用类型断言冒充数据转换。换来的题必须带 question 题型才能正确
        // 展示/提交/进结果页，刷新后由后端从 attempt.item_snapshot 恢复。
        const q = data.question
        const extraItem: PlanItem = {
          type: "question",
          id: q.id,
          text: q.text,
          band: q.band,
          audio_url: q.audio_url,
          suggested_seconds: q.suggested_seconds,
          // 分级题型训练：换一题保留考试字段（话题卡/准备时间不丢）
          exam_kind: q.exam_kind ?? null,
          exam_level: q.exam_level ?? null,
          cue_card_bullets: q.cue_card_bullets ?? null,
          prep_seconds: q.prep_seconds ?? null,
        }
        onExtraQuestion(extraItem)
        queryClient.invalidateQueries({ queryKey: todayQueryKey })
      } else {
        toast.info(
          t({
            zh: "这个主题的题已练完",
            en: "You've finished the questions on this topic",
          }),
          {
            description: t({
              zh: "可以重录上一题继续 polish",
              en: "Re-record the last one to keep polishing",
            }),
          },
        )
      }
    },
  })

  // 结果页「换同主题下一问」跳转过来（?next=1）时执行换题（闩锁保证只触发一次）
  const nextFlagConsumedRef = useRef(false)
  useEffect(() => {
    // 等计划加载后再换题：否则 plan?.session_id 为空，探索轮会取错主题
    if (
      nextFlag &&
      !nextFlagConsumedRef.current &&
      studentReady &&
      planLoaded &&
      !hasExam
    ) {
      nextFlagConsumedRef.current = true
      nextQuestionMutation.mutate()
    }
  }, [nextFlag, studentReady, planLoaded, hasExam, nextQuestionMutation])

  // ?next=1 但计划加载失败：提示换题未成功（否则静默无反应）
  useEffect(() => {
    if (nextFlag && planError) {
      toast.error(t({ zh: "换题失败", en: "Couldn't switch question" }), {
        description: t({
          zh: "练习计划加载失败，请返回重试",
          en: "The practice plan failed to load — please go back and retry",
        }),
      })
    }
  }, [nextFlag, planError, t])

  return { nextQuestionMutation }
}
