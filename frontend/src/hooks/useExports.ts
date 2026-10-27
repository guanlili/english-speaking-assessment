import { useQuery } from "@tanstack/react-query"

import { type ExportJobsPublic, ExportsService } from "@/client"
import { isLoggedIn } from "@/hooks/useAuth"

export const exportsQueryKey = ["exports"] as const

export function useExports(enabled = true) {
  return useQuery<ExportJobsPublic>({
    queryKey: exportsQueryKey,
    queryFn: () => ExportsService.listExports(),
    enabled: enabled && isLoggedIn(),
    refetchInterval: (query) => {
      const rows = query.state.data?.data ?? []
      const live = rows.some(
        (row) => row.status === "queued" || row.status === "running",
      )
      return live ? 2000 : 30_000
    },
  })
}
