import { createFileRoute, useParams } from "@tanstack/react-router"

import StudentShell from "@/components/Practice/StudentShell"
import LeaderboardStudentPanel from "@/components/Vocabulary/Leaderboard/LeaderboardStudentPanel"
import { APP_NAME } from "@/config"

export const Route = createFileRoute("/vocab/$code/leaderboard")({
  component: VocabLeaderboardPage,
  head: () => ({
    meta: [{ title: `班内学习榜 / Class Learning Board - ${APP_NAME}` }],
  }),
})

function VocabLeaderboardPage() {
  const { code } = useParams({ from: "/vocab/$code/leaderboard" })
  return (
    <StudentShell active="vocab">
      <LeaderboardStudentPanel code={code} />
    </StudentShell>
  )
}
