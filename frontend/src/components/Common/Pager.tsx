import { ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

/**
 * 服务端分页条（管理列表公用，批次 10-10）。
 *
 * - count 由服务端返回（反映过滤后总数）；pageIndex 从 0 起
 * - placeholder（keepPreviousData 旧页）期间禁用翻页：避免慢翻页下
 *   对旧页数据的误操作与错位跳页（同批次09 R13 的教训）
 * - 触控目标 44px（h-11）；全站双语
 */
export function Pager({
  pageIndex,
  pageSize,
  count,
  isPlaceholder = false,
  onChange,
}: {
  pageIndex: number
  pageSize: number
  count: number
  isPlaceholder?: boolean
  onChange: (pageIndex: number) => void
}) {
  const { t } = useI18n()
  const totalPages = Math.max(1, Math.ceil(count / pageSize))
  const atEnd = (pageIndex + 1) * pageSize >= count
  const disabled = isPlaceholder
  return (
    <nav
      aria-label={t({ zh: "分页", en: "Pagination" })}
      className="flex flex-wrap items-center justify-between gap-3 pt-2"
    >
      <span className="text-sm text-muted-foreground">
        {t({
          zh: `共 ${count} 条 · 第 ${pageIndex + 1}/${totalPages} 页`,
          en: `${count} items · Page ${pageIndex + 1}/${totalPages}`,
        })}
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          className="h-11"
          disabled={disabled || pageIndex === 0}
          onClick={() => onChange(pageIndex - 1)}
        >
          <ChevronLeft className="size-4" aria-hidden />
          {t({ zh: "上一页", en: "Previous" })}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-11"
          disabled={disabled || atEnd}
          onClick={() => onChange(pageIndex + 1)}
        >
          {t({ zh: "下一页", en: "Next" })}
          <ChevronRight className="size-4" aria-hidden />
        </Button>
      </div>
    </nav>
  )
}

export default Pager
