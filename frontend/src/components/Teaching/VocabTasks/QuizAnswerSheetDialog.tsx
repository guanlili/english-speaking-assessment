import { useQuery } from "@tanstack/react-query"
import { CheckCircle2 } from "lucide-react"
import { useState } from "react"
import type { VocabularyStudentResultRow } from "@/client"
import { VocabularyService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"

/** 学生答卷查看（教师端，不受公布规则约束；可切换补考轮次） */
export function QuizAnswerSheetDialog({
  code,
  assignmentId,
  student,
  roundNo,
  onClose,
}: {
  code: string
  assignmentId: string
  student: VocabularyStudentResultRow | null
  roundNo: number | null
  onClose: () => void
}) {
  const { t } = useI18n()
  const [selectedRound, setSelectedRound] = useState<number | null>(roundNo)
  const effectiveRound = selectedRound ?? roundNo
  const sheetQuery = useQuery({
    queryKey: [
      "vocab-teacher",
      code,
      "answer-sheet",
      student?.student_id,
      effectiveRound,
    ],
    queryFn: () =>
      VocabularyService.readQuizAnswerSheet({
        code: code.toUpperCase(),
        assignmentId,
        studentId: student?.student_id as string,
        roundNo: effectiveRound ?? undefined,
      }),
    enabled: student !== null,
  })
  if (student === null) return null
  const plan = sheetQuery.data

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {t({ zh: "学生答卷", en: "Student answer sheet" })} ·{" "}
            {student.display_name}
            {student.suffix ? `·${student.suffix}` : ""}
          </DialogTitle>
          <DialogDescription>
            {t({
              zh: "教师视角全量揭示，不受公布规则影响；此处成绩按该份答卷计。",
              en: "Teacher view reveals everything regardless of publishing; the score shown is for this attempt.",
            })}
          </DialogDescription>
        </DialogHeader>
        {(student.rounds ?? []).length > 1 && (
          <div className="flex flex-wrap gap-1.5">
            {(student.rounds ?? []).map((round) => (
              <Button
                key={round.round_no}
                size="sm"
                variant={
                  (effectiveRound ?? round.round_no) === round.round_no
                    ? "default"
                    : "outline"
                }
                onClick={() => setSelectedRound(round.round_no)}
              >
                R{round.round_no}
              </Button>
            ))}
          </div>
        )}
        {sheetQuery.isPending ? (
          <div role="status" className="py-6 text-sm text-muted-foreground">
            {t({ zh: "正在加载答卷…", en: "Loading answer sheet…" })}
          </div>
        ) : sheetQuery.isError || !plan ? (
          <p role="alert" className="py-6 text-sm text-muted-foreground">
            {t({
              zh: "答卷加载失败。",
              en: "Failed to load the answer sheet.",
            })}
          </p>
        ) : (
          <div className="space-y-3">
            <div className="rounded-2xl bg-secondary/50 p-4">
              <p className="text-sm font-semibold">
                {t({ zh: "成绩", en: "Score" })}{" "}
                {plan.is_quiz ? (
                  <span className="text-muted-foreground">
                    {t({
                      zh: `（本份答卷，第 ${plan.round_no ?? 1} 轮）`,
                      en: ` (this attempt, round ${plan.round_no ?? 1})`,
                    })}
                  </span>
                ) : null}
              </p>
              <p className="mt-1 text-2xl font-bold tabular-nums">
                {(plan.total_count ?? 0) > 0
                  ? Math.round(
                      ((plan.correct_first_count ?? 0) /
                        (plan.total_count ?? 1)) *
                        100,
                    )
                  : 0}
                %{" "}
                <span className="text-sm font-normal text-muted-foreground">
                  {t({
                    zh: `首答正确 ${plan.correct_first_count ?? 0}/${plan.total_count ?? 0} · 已答 ${plan.answered_count ?? 0}`,
                    en: `first-try ${plan.correct_first_count ?? 0}/${plan.total_count ?? 0} · answered ${plan.answered_count ?? 0}`,
                  })}
                </span>
              </p>
            </div>
            <ul className="space-y-1.5">
              {(plan.items ?? []).map((item) => (
                <li
                  key={item.item_index}
                  className="flex flex-wrap items-baseline gap-x-2 rounded-xl border px-3 py-2"
                >
                  <span className="text-xs text-muted-foreground">
                    #{item.item_index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm">
                    {item.meaning_zh}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {item.first_answer ?? "–"}
                  </span>
                  <span className="font-mono text-sm font-semibold">
                    {item.headword ?? "–"}
                  </span>
                  {item.answered ? (
                    item.is_correct ? (
                      <CheckCircle2 className="size-4 shrink-0 text-primary" />
                    ) : (
                      <span className="text-xs text-amber-600">
                        {t({ zh: "错", en: "miss" })}
                      </span>
                    )
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      {t({ zh: "未答", en: "none" })}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
