import { useNavigate } from "@tanstack/react-router"
import { useI18n } from "@/lib/i18n"

/** 轮次切换：回看各轮记录；当前展示轮高亮（多轮时渲染）。 */
export default function RoundSwitcher({
  code,
  assignmentId,
  rounds,
  activeRoundNo,
  currentRoundNo,
}: {
  code: string
  /** 跳转时要固定在 URL 的任务 id（assignmentParam ?? assignment.id） */
  assignmentId: string
  rounds: Array<{
    round_no: number
    correct_first_count: number
    answered_count: number
    status: string
  }>
  activeRoundNo: number | null
  currentRoundNo: number | null
}) {
  const { t } = useI18n()
  const navigate = useNavigate({ from: "/vocab/$code/practice" })
  if (rounds.length <= 1) return null
  return (
    <ul
      className="flex flex-wrap gap-1.5"
      aria-label={t({ zh: "轮次列表", en: "Round list" })}
    >
      {rounds.map((round) => {
        const isActive = round.round_no === activeRoundNo
        return (
          <li key={round.round_no}>
            <button
              type="button"
              aria-current={isActive ? "true" : undefined}
              onClick={() =>
                void navigate({
                  to: "/vocab/$code/practice",
                  params: { code },
                  search: {
                    assignment: assignmentId,
                    ...(round.round_no === currentRoundNo
                      ? {}
                      : { round: String(round.round_no) }),
                  },
                })
              }
              className={`h-11 rounded-xl border px-3 text-sm font-semibold transition-colors ${
                isActive
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:border-primary/40"
              }`}
            >
              {t({
                zh: `第 ${round.round_no} 轮 ${round.correct_first_count}/${round.answered_count}${round.status === "submitted" ? "" : " · 进行中"}`,
                en: `R${round.round_no} ${round.correct_first_count}/${round.answered_count}${round.status === "submitted" ? "" : " · open"}`,
              })}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
