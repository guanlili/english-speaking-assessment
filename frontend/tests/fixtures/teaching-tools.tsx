import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createRoot } from "react-dom/client"
import { Toaster } from "sonner"
import { AdminService, type AttemptPublic, type BoardStudent } from "@/client"
import { AttemptComparison } from "@/components/Practice/AttemptComparison"
import { DevicePreflight } from "@/components/Practice/DevicePreflight"
import { LearningReportCard } from "@/components/Practice/LearningReportCard"
import { PublishedClassSummaries } from "@/components/Practice/PublishedClassSummaries"
import { StudentClassroomInbox } from "@/components/Practice/StudentClassroomInbox"
import { ClassroomContactPanel } from "@/components/Teaching/ClassroomContactPanel"
import { ClassroomLiveStatus } from "@/components/Teaching/ClassroomLiveStatus"
import { CopyContentButton } from "@/components/Teaching/CopyContentButton"
import { FollowupManager } from "@/components/Teaching/FollowupManager"
import { LessonReview } from "@/components/Teaching/LessonReview"
import { TeacherFeedbackEditor } from "@/components/Teaching/TeacherFeedbackEditor"
import { I18nProvider } from "@/lib/i18n"
import "./teaching-tools.css"

const student: BoardStudent = {
  student_id: "alice",
  display_name: "Alice Private Name",
  done_count: 1,
  total_count: 2,
  has_pending: false,
  items: [
    { item_id: "item", type: "question", status: "done", attempt_id: "answer" },
  ],
}
const p1 = new URLSearchParams(location.search).has("p1")
const students = p1
  ? [student, { ...student, student_id: "ben", display_name: "Ben", items: [] }]
  : [student]
const attempt: AttemptPublic = {
  id: "answer",
  item_id: "item",
  item_type: "question",
  status: "done",
  engine: "mock",
  duration_s: 3,
  overall: 80,
}
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})
createRoot(document.getElementById("root")!).render(
  <I18nProvider>
    <QueryClientProvider client={queryClient}>
      <main className="mx-auto max-w-5xl space-y-6 p-4">
        <ClassroomLiveStatus
          code="COACH"
          students={students}
          onStudent={() => {}}
        />
        <LessonReview
          code="COACH"
          exerciseId="source"
          students={students}
          isExam={false}
        />
        <FollowupManager
          code="COACH"
          students={students}
          currentExerciseId="source"
        />
        <LearningReportCard code="COACH" studentId="alice" />
        <CopyContentButton
          label="复制为我的版本"
          copy={() =>
            AdminService.copySchoolContent({ kind: "question", itemId: "item" })
          }
          onCopied={() => {}}
          source={{ kind: "question", id: "source-item" }}
        />
        <AttemptComparison attemptId="answer" />
        <TeacherFeedbackEditor attempt={attempt} reload={() => {}} />
        <DevicePreflight code="COACH" />
        {p1 && (
          <>
            <ClassroomContactPanel code="COACH" students={students} />
            <StudentClassroomInbox code="COACH" />
            <PublishedClassSummaries code="COACH" />
          </>
        )}
      </main>
      <Toaster />
    </QueryClientProvider>
  </I18nProvider>,
)
