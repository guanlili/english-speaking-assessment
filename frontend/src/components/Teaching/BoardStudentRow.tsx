import { Link } from "@tanstack/react-router"
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { BoardStudent } from "@/client"
import AttemptAudio from "@/components/Practice/AttemptAudio"
import { AttemptFeedbackDialog } from "@/components/Teaching/AttemptFeedbackDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { TableCell, TableRow } from "@/components/ui/table"
import {
  boardStudentDisplayName,
  boardStudentFeedbackMessage,
} from "@/lib/board-copy"
import { copyText } from "@/lib/clipboard"
import { useI18n } from "@/lib/i18n"
import { ITEM_TYPE_LABELS, TERMS } from "@/lib/terms"

/**
 * 今日名单的单行（展示组件）：点击整行或左侧按钮展开每题分数与音频，
 * 展开区提供进步轨迹入口与一键复制反馈文案。
 */
export function BoardStudentRow({
  student,
  code,
  expanded,
  onToggle,
  isExamPublish,
}: {
  student: BoardStudent
  code: string
  expanded: boolean
  onToggle: () => void
  isExamPublish: boolean
}) {
  const { t } = useI18n()
  const name = boardStudentDisplayName(student)
  const [feedbackAttemptId, setFeedbackAttemptId] = useState<string | null>(
    null,
  )

  return (
    <>
      <TableRow onClick={onToggle} className="cursor-pointer">
        <TableCell>
          <button
            type="button"
            aria-expanded={expanded}
            aria-label={
              expanded
                ? t({
                    zh: `收起 ${name} 的详情`,
                    en: `Collapse details for ${name}`,
                  })
                : t({
                    zh: `展开 ${name} 的详情`,
                    en: `Expand details for ${name}`,
                  })
            }
            onClick={(e) => {
              e.stopPropagation()
              onToggle()
            }}
            className="grid size-9 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-primary"
          >
            {expanded ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </button>
        </TableCell>
        <TableCell className="font-medium">{name}</TableCell>
        <TableCell>
          {student.done_count}/{student.total_count}
        </TableCell>
        <TableCell>{student.repeat_avg ?? "–"}</TableCell>
        <TableCell>{student.question_avg ?? "–"}</TableCell>
        <TableCell className="space-x-1 whitespace-nowrap">
          {isExamPublish && (
            <Badge
              variant={student.exam_tab_switches ? "destructive" : "outline"}
            >
              {student.exam_tab_switches === null || undefined
                ? t({ zh: "未开考", en: "Not started" })
                : `${t({ zh: "切屏", en: "Switches" })} ${student.exam_tab_switches}`}
            </Badge>
          )}
          {isExamPublish && student.exam_time_used_seconds != null && (
            <Badge variant="secondary">
              {student.exam_ended
                ? `${t({ zh: "已交卷", en: "Submitted" })} · ${formatExamUsed(student.exam_time_used_seconds)}`
                : `${t({ zh: "用时", en: "Elapsed" })} ${formatExamUsed(student.exam_time_used_seconds)}`}
            </Badge>
          )}
          {student.inactive_days7 && (
            <Badge variant="destructive">
              {t({ zh: "7 日未练", en: "Inactive 7 Days" })}
            </Badge>
          )}
          {student.has_pending ? (
            <Badge variant="secondary">
              {t({ zh: "评分中", en: "Scoring" })}
            </Badge>
          ) : student.done_count === 0 ? (
            <span className="text-muted-foreground">
              {t({ zh: "未提交", en: "Not submitted" })}
            </span>
          ) : (
            <Badge variant="outline">
              {t({ zh: "已提交", en: "Submitted" })}
            </Badge>
          )}
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow>
          <TableCell colSpan={6}>
            {/* biome-ignore lint/a11y/noStaticElementInteractions: stop click bubbling to row toggle */}
            <div
              className="space-y-2 py-1"
              onMouseDown={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between">
                <div className="flex flex-wrap gap-2">
                  <Button variant="link" size="sm" asChild>
                    <Link
                      to="/t/$code/s/$studentId"
                      params={{ code, studentId: student.student_id }}
                    >
                      {t({
                        zh: "查看进步轨迹 →",
                        en: "View Progress Trail →",
                      })}
                    </Link>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={async (event) => {
                      event.stopPropagation()
                      const feedback = boardStudentFeedbackMessage(student, t)
                      if (await copyText(feedback)) {
                        toast.success(
                          t({
                            zh: "反馈文案已复制",
                            en: "Feedback text copied",
                          }),
                          {
                            description: feedback,
                          },
                        )
                      } else {
                        toast.error(
                          t({
                            zh: "复制失败，请重试",
                            en: "Copy failed, please try again",
                          }),
                        )
                      }
                    }}
                  >
                    {t({ zh: "复制反馈", en: "Copy Feedback" })}
                  </Button>
                </div>
              </div>
              {student.items
                .filter((i) => i.type !== "instruction")
                .every((i) => i.status === "missing") && (
                <p className="text-sm text-muted-foreground">
                  {t({ zh: "还没有作答。", en: "No answers yet." })}
                </p>
              )}
              {student.items.map((item, index) => (
                <div
                  key={item.item_id}
                  className="flex flex-wrap items-center gap-3 rounded-md border px-3 py-2"
                >
                  <span className="w-20 text-sm text-muted-foreground">
                    {index + 1}.{" "}
                    {t(
                      ITEM_TYPE_LABELS[item.type] ?? {
                        zh: item.type,
                        en: item.type,
                      },
                    )}
                  </span>
                  {item.type === "instruction" ? (
                    item.status === "done" ? (
                      <span className="text-sm font-medium text-primary">
                        {t({ zh: "已读", en: "Read" })}
                      </span>
                    ) : (
                      <span className="text-sm text-muted-foreground">
                        {t({ zh: "未读", en: "Unread" })}
                      </span>
                    )
                  ) : item.status === "missing" ? (
                    <span className="text-sm text-muted-foreground">
                      {t({ zh: "未做", en: "Missing" })}
                    </span>
                  ) : item.status === "done" ? (
                    <span className="text-sm font-semibold tabular-nums">
                      {t(TERMS.score)} {item.overall ?? "–"}
                    </span>
                  ) : item.status === "failed" ? (
                    <span className="text-sm text-destructive">
                      {t({ zh: "未评出", en: "No Score" })}
                    </span>
                  ) : (
                    <span className="text-sm text-muted-foreground">
                      <Loader2 className="mr-1 inline size-3 animate-spin" />
                      {t({ zh: "评分中", en: "Scoring" })}
                    </span>
                  )}
                  {item.attempt_id && item.status === "done" && (
                    <>
                      <AttemptAudio
                        attemptId={item.attempt_id}
                        className="h-8"
                      />
                      <Button
                        variant="ghost"
                        size="sm"
                        className="min-h-11"
                        onClick={(e) => {
                          e.stopPropagation()
                          setFeedbackAttemptId(item.attempt_id!)
                        }}
                      >
                        {t({ zh: "详细反馈", en: "Detailed Feedback" })}
                      </Button>
                    </>
                  )}
                </div>
              ))}
              <AttemptFeedbackDialog
                attemptId={feedbackAttemptId}
                open={feedbackAttemptId !== null}
                onClose={() => setFeedbackAttemptId(null)}
              />
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}

/** 考试用时（m:ss）。秒为整数的输入与 lib/time 的 formatSeconds 等价，逐字保留原实现。 */
function formatExamUsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, "0")}`
}
