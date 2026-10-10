import { Download, Link2, Search } from "lucide-react"
import type { BoardStudent } from "@/client"
import { BoardStudentRow } from "@/components/Teaching/BoardStudentRow"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { BOARD_STATUS_LABELS } from "@/lib/board-copy"
import { useI18n } from "@/lib/i18n"

/**
 * 今日名单卡片（展示组件）：状态筛选 + 姓名搜索 + 学生入口/导出操作条，
 * 以及三种列表形态（无学生 / 无匹配 / 名单表格）。筛选状态由页面持有。
 */
export function BoardRosterCard({
  code,
  hasStudents,
  filteredStudents,
  totalStudents,
  statusFilter,
  onStatusFilterChange,
  nameQuery,
  onNameQueryChange,
  onClearFilters,
  isExamPublish,
  expandedId,
  onToggleRow,
  onShareLink,
  onExportCsv,
}: {
  code: string
  hasStudents: boolean
  filteredStudents: BoardStudent[]
  totalStudents: number
  statusFilter: string
  onStatusFilterChange: (value: string) => void
  nameQuery: string
  onNameQueryChange: (value: string) => void
  onClearFilters: () => void
  isExamPublish: boolean
  expandedId: string | null
  onToggleRow: (studentId: string) => void
  onShareLink: () => void
  onExportCsv: () => void
}) {
  const { t } = useI18n()
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t({ zh: "今日名单", en: "Today's Roster" })}
        </CardTitle>
        <CardDescription>
          {t({
            zh: "点击一行展开每题分数和音频。分数是参考反馈，不是考试成绩。",
            en: "Click a row to expand per-item scores and audio. Scores are reference feedback, not exam grades.",
          })}
          <span className="mt-1 block sm:hidden">
            {t({
              zh: "横向滑动表格，可以查看完整成绩与状态。",
              en: "Swipe the table sideways to see all scores and statuses.",
            })}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="pb-0">
        <div className="flex flex-wrap items-center gap-2 pb-3">
          <select
            value={statusFilter}
            onChange={(e) => onStatusFilterChange(e.target.value)}
            aria-label={t({
              zh: "练习状态筛选",
              en: "Filter by practice status",
            })}
            className="h-11 rounded-xl border border-input bg-card px-3 text-base text-foreground transition-colors hover:border-primary/35"
          >
            {Object.entries(BOARD_STATUS_LABELS).map(([v, label]) => (
              <option key={v} value={v}>
                {t(label)}
              </option>
            ))}
          </select>
          <div className="relative min-w-40 flex-1 sm:max-w-64">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-3.5 size-4 text-muted-foreground"
            />
            <Input
              type="search"
              value={nameQuery}
              onChange={(e) => onNameQueryChange(e.target.value)}
              placeholder={t({
                zh: "搜索学生姓名",
                en: "Search student names",
              })}
              aria-label={t({
                zh: "搜索学生姓名",
                en: "Search student names",
              })}
              className="pl-9"
            />
          </div>
          <span role="status" className="text-xs text-muted-foreground">
            {t({
              zh: `${filteredStudents.length} / ${totalStudents} 人`,
              en: `${filteredStudents.length} / ${totalStudents}`,
            })}
          </span>
          {(nameQuery || statusFilter !== "all") && (
            <Button variant="ghost" size="sm" onClick={onClearFilters}>
              {t({ zh: "清除筛选", en: "Clear Filters" })}
            </Button>
          )}
          <div className="ml-auto flex gap-2">
            <Button variant="outline" size="sm" onClick={onShareLink}>
              <Link2 />
              {t({ zh: "学生入口", en: "Student Entry" })}
            </Button>
            <Button variant="outline" size="sm" onClick={onExportCsv}>
              <Download />
              {t({ zh: "导出", en: "Export" })}
            </Button>
          </div>
        </div>
      </CardContent>
      <CardContent>
        {!hasStudents ? (
          <p className="py-8 text-center text-muted-foreground">
            {t({
              zh: "还没有学生进入这个课堂。",
              en: "No students have joined this classroom yet.",
            })}
          </p>
        ) : filteredStudents.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-2xl bg-background px-4 py-10 text-center">
            <Search
              className="size-7 text-muted-foreground"
              aria-hidden="true"
            />
            <p className="text-sm font-semibold">
              {t({
                zh: "没有找到符合条件的学生",
                en: "No matching students",
              })}
            </p>
            <p className="text-xs text-muted-foreground">
              {t({
                zh: "试试其他姓名，或清除筛选查看全部学生。",
                en: "Try another name, or clear filters to see all students.",
              })}
            </p>
            <Button variant="outline" size="sm" onClick={onClearFilters}>
              {t({ zh: "查看全部学生", en: "View All Students" })}
            </Button>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>{t({ zh: "姓名", en: "Name" })}</TableHead>
                <TableHead>{t({ zh: "完成", en: "Done" })}</TableHead>
                <TableHead>
                  {t({
                    zh: "跟读参考分",
                    en: "Repeat Reference Score",
                  })}
                </TableHead>
                <TableHead>
                  {t({
                    zh: "问答参考分",
                    en: "Scenario Q&A Reference Score",
                  })}
                </TableHead>
                <TableHead>{t({ zh: "状态", en: "Status" })}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredStudents.map((student) => (
                <BoardStudentRow
                  key={student.student_id}
                  student={student}
                  code={code}
                  isExamPublish={isExamPublish}
                  expanded={expandedId === student.student_id}
                  onToggle={() => onToggleRow(student.student_id)}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
