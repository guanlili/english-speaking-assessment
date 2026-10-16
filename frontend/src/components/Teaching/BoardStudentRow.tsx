import { Link } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageSquareText,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { BoardStudent } from "@/client"
import { AttemptFeedbackDialog } from "@/components/Teaching/AttemptFeedbackDialog"
import { RecordingButton } from "@/components/Teaching/RecordingButton"
import { StudentFeedbackDialog } from "@/components/Teaching/StudentFeedbackDialog"
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
  const [summaryOpen, setSummaryOpen] = useState(false)
  const name = boardStudentDisplayName(student)
  const [feedbackAttemptId, setFeedbackAttemptId] = useState<string | null>(
    null,
  )

  return (
    <>
      <TableRow
        id={`student-${student.student_id}`}
        onClick={onToggle}
        data-state={expanded ? "selected" : undefined}
        className="grid cursor-pointer grid-cols-[2.75rem_minmax(0,1fr)_auto] gap-y-3 p-4 hover:bg-secondary/30 lg:table-row lg:p-0"
      >
        <TableCell className="block p-0 lg:table-cell lg:w-12 lg:py-4 lg:pl-3 lg:pr-0">
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
            className="grid size-11 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-secondary hover:text-primary focus-visible:outline-2 focus-visible:outline-ring"
          >
            {expanded ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </button>
        </TableCell>
        <TableCell className="block min-w-0 p-0 font-medium lg:table-cell lg:px-4 lg:py-4">
          <div className="flex min-w-0 items-center gap-2.5">
            <span
              aria-hidden="true"
              className="hidden size-9 shrink-0 items-center justify-center rounded-full border border-primary/10 bg-secondary text-xs font-semibold text-primary lg:flex"
            >
              {student.display_name.trim().slice(0, 1).toUpperCase()}
            </span>
            <div className="min-w-0">
              <span className="block break-words whitespace-normal leading-5">
                {name}
              </span>
              {student.items.some((item) => item.teacher_focus) && (
                <span className="text-xs font-medium text-primary">
                  {t({ zh: "教师重点关注", en: "Teacher focus area" })}
                </span>
              )}
              <Button
                variant="ghost"
                size="sm"
                className="mt-1 flex min-h-11 gap-1.5 px-0 text-xs font-medium text-primary hover:bg-transparent hover:underline"
                onClick={(event) => {
                  event.stopPropagation()
                  setSummaryOpen(true)
                }}
              >
                <MessageSquareText aria-hidden="true" className="size-3.5" />
                {t({ zh: "汇总反馈", en: "Overall feedback" })}
              </Button>
            </div>
          </div>
        </TableCell>
        <TableCell className="block p-0 text-right lg:table-cell lg:px-4 lg:py-4 lg:text-left">
          <p className="mb-1 text-[11px] text-muted-foreground lg:hidden">
            {t({ zh: "完成", en: "Done" })}
          </p>
          <p className="text-sm font-medium tabular-nums">
            {student.done_count}
            <span className="text-muted-foreground">
              /{student.total_count}
            </span>
          </p>
          <div
            aria-hidden="true"
            className="mt-2 flex h-1.5 w-14 overflow-hidden rounded-full bg-muted lg:w-16"
          >
            <div
              className="rounded-full bg-primary/70"
              style={{
                width: `${student.total_count > 0 ? Math.min(100, Math.max(0, (student.done_count / student.total_count) * 100)) : 0}%`,
              }}
            />
          </div>
        </TableCell>
        <TableCell className="col-start-2 block p-0 lg:table-cell lg:px-4 lg:py-4">
          <span className="mb-1 block text-[11px] text-muted-foreground lg:hidden">
            {t({ zh: "跟读参考分", en: "Repeat score" })}
          </span>
          <span className="font-medium tabular-nums">
            {student.repeat_avg ?? "–"}
          </span>
        </TableCell>
        <TableCell className="block p-0 text-right lg:table-cell lg:px-4 lg:py-4 lg:text-left">
          <span className="mb-1 block text-[11px] text-muted-foreground lg:hidden">
            {t({ zh: "问答参考分", en: "Q&A score" })}
          </span>
          <span className="font-medium tabular-nums">
            {student.question_avg ?? "–"}
          </span>
        </TableCell>
        <TableCell className="col-span-2 col-start-2 flex flex-wrap items-center gap-1.5 p-0 lg:table-cell lg:max-w-56 lg:space-x-1 lg:whitespace-normal lg:px-4 lg:py-4 [&_[data-slot=badge]]:my-0.5">
          {isExamPublish && (
            <Badge
              variant={student.exam_tab_switches ? "destructive" : "outline"}
            >
              {student.exam_tab_switches == null
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
        <TableRow className="block bg-muted/20 hover:bg-muted/20 lg:table-row">
          <TableCell
            colSpan={6}
            className="block whitespace-normal p-3 lg:table-cell lg:p-5"
          >
            {/* biome-ignore lint/a11y/noStaticElementInteractions: stop click bubbling to row toggle */}
            <div
              className="min-w-0 space-y-3 py-1"
              onMouseDown={(e) => e.stopPropagation()}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-2">
                  <Button variant="link" size="sm" className="min-h-11" asChild>
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
                    className="min-h-11"
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
                  className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-border/70 bg-card px-4 py-3"
                >
                  <span className="min-w-24 flex-1 text-sm font-medium leading-6 text-muted-foreground">
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
                  {item.attempt_id && item.type !== "instruction" && (
                    <>
                      <RecordingButton
                        key={item.attempt_id}
                        attemptId={item.attempt_id}
                        label={t({
                          zh: `回听 ${name} 第${index + 1}题录音`,
                          en: `Listen to ${name}'s recording for item ${index + 1}`,
                        })}
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
      {summaryOpen && (
        <StudentFeedbackDialog
          name={name}
          items={student.items}
          open={summaryOpen}
          onClose={() => setSummaryOpen(false)}
        />
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
