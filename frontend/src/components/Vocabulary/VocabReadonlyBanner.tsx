import { History } from "lucide-react"

import { useModules } from "@/hooks/useModules"
import { useI18n } from "@/lib/i18n"

/**
 * 词汇模块只读横幅（#567 第 3 项）：模块非 active（未开通/关闭/待生效/到期）时，
 * 词汇页顶部提示「仅可查看历史记录与导出」；写入口由各页面按同一只读口径隐藏。
 * active 或清单加载中不渲染。文案双语，供外教查看。
 */
export function VocabReadonlyBanner() {
  const { t } = useI18n()
  const { readonlyOf, isPending } = useModules()
  const status = readonlyOf("vocabulary")

  if (isPending || !status) return null

  const expired = status.state === "expired"
  const line = expired
    ? {
        zh: "词汇模块已到期，仅可查看历史记录与导出，不能开始新的练习。",
        en: "The vocabulary module has expired. History records and exports are available in read-only mode; new practice is closed.",
      }
    : {
        zh: "词汇模块未开通，仅可查看历史记录与导出，不能开始新的练习。",
        en: "The vocabulary module is not enabled. History records and exports are available in read-only mode; new practice is closed.",
      }

  return (
    <div
      data-testid="vocab-readonly-banner"
      role="status"
      className="flex items-start gap-3 rounded-2xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200"
    >
      <History className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <p className="leading-6">{t(line)}</p>
    </div>
  )
}
