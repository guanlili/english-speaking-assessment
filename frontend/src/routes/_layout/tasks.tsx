import { createFileRoute } from "@tanstack/react-router"

import { TeachingTaskCenter } from "@/components/Teaching/TeachingTaskCenter"
import { APP_NAME } from "@/config"

export const Route = createFileRoute("/_layout/tasks")({
  component: TeachingTaskCenter,
  head: () => ({
    meta: [{ title: `教学任务中心 / Teaching Tasks - ${APP_NAME}` }],
  }),
})
