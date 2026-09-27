import { useQuery } from "@tanstack/react-query"
import { LoginService } from "@/client"

export default function useLoginOptions() {
  return useQuery({
    queryKey: ["login-options"],
    queryFn: () => LoginService.readLoginOptions(),
    retry: false,
    staleTime: 60_000,
  })
}
