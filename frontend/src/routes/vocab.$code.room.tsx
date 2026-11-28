import { createFileRoute, useParams } from "@tanstack/react-router"
import StudentShell from "@/components/Practice/StudentShell"
import RoomPlayer from "@/components/Vocabulary/Pk/RoomPlayer"

export const Route = createFileRoute("/vocab/$code/room")({
  component: VocabRoomPage,
  head: () => ({
    meta: [{ title: "课堂大屏 PK - Speaking Assessment" }],
  }),
})

function VocabRoomPage() {
  const { code } = useParams({ from: "/vocab/$code/room" })
  return (
    <StudentShell active="vocab">
      <RoomPlayer code={code} />
    </StudentShell>
  )
}
