import { useQuery } from "@tanstack/react-query"
import { AdminService, ClassesService } from "@/client"

export function useLessonContent(code: string) {
  const units = useQuery({
    queryKey: ["teacher", "units", code],
    queryFn: () => ClassesService.listUnitsForClass({ code }),
  })
  const passages = useQuery({
    queryKey: ["admin", "passages"],
    queryFn: () => AdminService.listPassages(),
  })
  const scenarios = useQuery({
    queryKey: ["admin", "scenarios"],
    queryFn: () => AdminService.listScenarios(),
  })
  return { units, passages, scenarios }
}
