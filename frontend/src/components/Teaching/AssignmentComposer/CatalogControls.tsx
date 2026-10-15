import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { ComposerPage } from "@/hooks/useComposerLibrary"
import { useI18n } from "@/lib/i18n"

export function CatalogControls({
  page,
  label,
}: {
  page: ComposerPage
  label: { zh: string; en: string }
}) {
  const { t } = useI18n()
  return (
    <fieldset className="space-y-2 rounded-xl border p-3" aria-label={t(label)}>
      <Input
        className="text-base"
        value={page.keyword}
        onChange={(e) => page.setKeyword(e.target.value)}
        aria-label={t(label)}
        placeholder={t(label)}
      />
      {page.failed && (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-sm">
          {t({
            zh: "题库加载失败，请重试。",
            en: "Could not load the question bank. Please retry.",
          })}
          <Button variant="outline" className="min-h-11" onClick={page.retry}>
            {t({ zh: "重试", en: "Retry" })}
          </Button>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span role="status" className="text-sm text-muted-foreground">
          {page.pending
            ? t({ zh: "正在加载…", en: "Loading…" })
            : t({ zh: `第 ${page.page + 1} 页`, en: `Page ${page.page + 1}` })}
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            className="min-h-11"
            disabled={page.pending || page.page === 0}
            onClick={() => page.setPage(page.page - 1)}
          >
            {t({ zh: "上一页", en: "Previous" })}
          </Button>
          <Button
            variant="outline"
            className="min-h-11"
            disabled={page.pending || !page.hasNext}
            onClick={() => page.setPage(page.page + 1)}
          >
            {t({ zh: "下一页", en: "Next" })}
          </Button>
        </div>
      </div>
    </fieldset>
  )
}
