import { createFileRoute, useParams } from "@tanstack/react-router"
import StudentShell from "@/components/Practice/StudentShell"
import PkArena from "@/components/Vocabulary/Pk/PkArena"

export const Route = createFileRoute("/vocab/$code/pk")({
  component: VocabPkPage,
  head: () => ({
    meta: [{ title: "课堂对战 PK - Speaking Assessment" }],
  }),
})

function VocabPkPage() {
  const { code } = useParams({ from: "/vocab/$code/pk" })
  return (
    <StudentShell active="vocab" wide>
      <PkArena code={code} />
    </StudentShell>
  )
}
