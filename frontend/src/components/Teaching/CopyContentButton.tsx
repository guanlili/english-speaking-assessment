import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"
import { type AdminCopySchoolContentData, AdminService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"
export function CopyContentButton({
  kind,
  itemId,
  copiedFromId,
}: {
  kind: AdminCopySchoolContentData["kind"]
  itemId: string
  copiedFromId?: string | null
}) {
  const { t } = useI18n()
  const client = useQueryClient()
  const [sourceOpen, setSourceOpen] = useState(false)
  const source = useQuery({
    queryKey: ["content-source", kind, copiedFromId],
    queryFn: () =>
      AdminService.readSharedContentSource({ kind, itemId: copiedFromId! }),
    enabled: sourceOpen && Boolean(copiedFromId),
    retry: false,
  })
  const mutation = useMutation({
    mutationFn: () => AdminService.copySchoolContent({ kind, itemId }),
    onSuccess: () => {
      void client.invalidateQueries({
        predicate: (query) =>
          query.queryKey.some(
            (key) =>
              typeof key === "string" &&
              /passage|sentence|question|scenario|instruction|composer/.test(
                key,
              ),
          ),
      })
      toast.success(
        t({
          zh: "已复制为你的可编辑版本，可在题库中查找并修改。",
          en: "Copied to your editable version. Find and edit it in the question bank.",
        }),
      )
    },
    onError: () =>
      toast.error(
        t({ zh: "复制失败，请重试。", en: "Copy failed. Please retry." }),
      ),
  })
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        variant="outline"
        className="min-h-11"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {t({ zh: "复制为我的版本", en: "Copy to my version" })}
      </Button>
      {copiedFromId && (
        <Button
          variant="ghost"
          className="min-h-11"
          onClick={() => setSourceOpen(true)}
        >
          {t({ zh: "查看副本来源", en: "View copy source" })}
        </Button>
      )}
      <Dialog open={sourceOpen} onOpenChange={setSourceOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "题目来源", en: "Source material" })}
            </DialogTitle>
            <DialogDescription>
              {t({
                zh: "这里展示来源题目的当前版本；副本独立保存，不会随来源变化。",
                en: "This is the current source material. Your copy is independent and does not change with the source.",
              })}
            </DialogDescription>
          </DialogHeader>
          {source.isPending ? (
            <p role="status">{t({ zh: "正在加载…", en: "Loading…" })}</p>
          ) : source.isError ? (
            <p role="alert">
              {t({
                zh: "来源已删除或暂时无法读取，副本仍可正常使用。",
                en: "The source was deleted or is unavailable. Your copy remains usable.",
              })}
            </p>
          ) : (
            <div className="space-y-3">
              <p className="font-medium">{source.data?.title}</p>
              <p>
                {source.data?.author_name ??
                  t({ zh: "校内公共材料", en: "Shared school material" })}
              </p>
              <p className="whitespace-pre-wrap break-words">
                {source.data?.text}
              </p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
