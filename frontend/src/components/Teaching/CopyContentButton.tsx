import {
  type QueryClient,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"
import { Copy, Loader2 } from "lucide-react"
import { useRef } from "react"
import { toast } from "sonner"
import { ApiError } from "@/client"
import {
  ContentSourceButton,
  type ContentSourceRef,
} from "@/components/Teaching/ContentSourceButton"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

export function invalidateContentQueries(client: QueryClient) {
  return Promise.all(
    [
      "passages",
      "sentences",
      "scenarios",
      "question-bank",
      "instructions",
      "topics",
      "units",
      "composer-selection",
    ].map((kind) => client.invalidateQueries({ queryKey: ["admin", kind] })),
  )
}

export function CopyContentButton<T>({
  copy,
  onCopied,
  onStart,
  label,
  source,
}: {
  copy: () => Promise<T>
  onCopied: (content: T) => void
  onStart?: () => void
  label: string
  source?: ContentSourceRef
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  // Block rapid clicks before React renders the pending state; never auto-retry a POST.
  const inFlight = useRef(false)
  const mutation = useMutation({
    mutationFn: copy,
    retry: false,
    onSuccess: (content) => {
      onCopied(content)
      void invalidateContentQueries(queryClient)
      toast.success(
        t({
          zh: "副本已创建，可立即改编",
          en: "Copy created and ready to edit",
        }),
      )
    },
    onSettled: () => {
      inFlight.current = false
    },
  })
  const errorStatus =
    mutation.error instanceof ApiError ? mutation.error.status : undefined
  const errorMessage =
    errorStatus === 404
      ? t({
          zh: "原内容已不存在，请刷新列表后重试",
          en: "The original no longer exists. Refresh the list and retry.",
        })
      : errorStatus === 403
        ? t({
            zh: "没有复制权限，请联系管理员",
            en: "You do not have permission to copy. Contact an administrator.",
          })
        : t({
            zh: "复制失败，请重试；原内容未改动",
            en: "Copy failed. Please retry; the original is unchanged.",
          })

  return (
    <span className="inline-flex max-w-full flex-col items-start gap-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="min-h-11 min-w-11"
        aria-label={label}
        aria-busy={mutation.isPending}
        disabled={mutation.isPending}
        onClick={(event) => {
          event.stopPropagation()
          if (inFlight.current) return
          inFlight.current = true
          onStart?.()
          mutation.mutate()
        }}
      >
        {mutation.isPending ? <Loader2 className="animate-spin" /> : <Copy />}
        {mutation.isPending
          ? t({ zh: "复制中…", en: "Copying…" })
          : t({ zh: "复制改编", en: "Copy & edit" })}
      </Button>
      {source && <ContentSourceButton source={source} />}
      {mutation.isError && (
        <span
          role="alert"
          className="max-w-64 text-left text-xs text-destructive"
        >
          {errorMessage}
        </span>
      )}
    </span>
  )
}
