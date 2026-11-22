import { createFileRoute, useParams } from "@tanstack/react-router"

import StudentShell from "@/components/Practice/StudentShell"
import FarmPanel from "@/components/Vocabulary/Farm/FarmPanel"

export const Route = createFileRoute("/vocab/$code/farm")({
  component: VocabFarmPage,
  head: () => ({
    meta: [{ title: "专注农场 - Speaking Assessment" }],
  }),
})

function VocabFarmPage() {
  const { code } = useParams({ from: "/vocab/$code/farm" })
  return (
    <StudentShell active="vocab">
      <FarmPanel code={code} />
    </StudentShell>
  )
}
