import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { type AdminReadSharedContentSourceData, AdminService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"
export type ContentSourceRef = {
  kind: AdminReadSharedContentSourceData["path"]["kind"]
  id: string
}
export function ContentSourceButton({ source }: { source: ContentSourceRef }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const query = useQuery({
    queryKey: ["content-source", source.kind, source.id],
    queryFn: () =>
      AdminService.readSharedContentSource({
        kind: source.kind,
        item_id: source.id,
      }),
    enabled: open,
    retry: false,
  })
  return (
    <>
      <Button
        variant="ghost"
        className="min-h-11"
        onClick={(event) => {
          event.stopPropagation()
          setOpen(true)
        }}
      >
        {t({ zh: "查看副本来源", en: "View copy source" })}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
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
          {query.isPending ? (
            <p role="status">{t({ zh: "正在加载…", en: "Loading…" })}</p>
          ) : query.isError ? (
            <p role="alert">
              {t({
                zh: "来源已删除或暂时无法读取，副本仍可正常使用。",
                en: "The source was deleted or is unavailable. Your copy remains usable.",
              })}
            </p>
          ) : (
            <div className="space-y-3">
              <p className="font-medium">{query.data?.title}</p>
              <p>
                {query.data?.author_name ??
                  t({
                    zh: "校内题库材料",
                    en: "School question-bank material",
                  })}
              </p>
              <p className="whitespace-pre-wrap break-words">
                {query.data?.text}
              </p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
