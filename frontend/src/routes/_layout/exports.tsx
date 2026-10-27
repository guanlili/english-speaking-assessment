import { createFileRoute } from "@tanstack/react-router"

import { ExportCenter } from "@/components/Exports/ExportCenter"
import { APP_NAME } from "@/config"

export const Route = createFileRoute("/_layout/exports")({
  component: TeacherExportsPage,
  head: () => ({
    meta: [{ title: `录音导出 / Audio Export - ${APP_NAME}` }],
  }),
})

function TeacherExportsPage() {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6 md:py-8">
      <ExportCenter mode="classroom" />
    </div>
  )
}
