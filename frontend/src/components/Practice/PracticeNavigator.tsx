import { type ReactNode, useRef } from "react"
import type { PlanItem } from "@/client"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

/** Practice navigation never acknowledges or submits the item being left. */
export default function PracticeNavigator({
  items,
  index,
  disabled,
  onSelect,
  children,
  hidden,
}: {
  items: PlanItem[]
  index: number
  disabled: boolean
  onSelect: (id: string) => void
  hidden?: boolean
  children: ReactNode
}) {
  const { t } = useI18n()
  const start = useRef<{ x: number; y: number } | null>(null)
  const select = (next: number) => {
    if (!disabled && items[next]) onSelect(items[next].id)
  }
  if (hidden) return children
  let number = 0
  return (
    <div className="grid gap-5">
      <nav
        aria-label={t({ zh: "练习选题", en: "Practice navigation" })}
        className="flex flex-wrap items-center gap-2"
      >
        <Button
          variant="outline"
          className="min-h-11"
          disabled={disabled || index === 0}
          onClick={() => select(index - 1)}
        >
          {t({ zh: "上一题", en: "Previous" })}
        </Button>
        <select
          aria-label={t({ zh: "选择练习题", en: "Select practice item" })}
          className="h-11 min-w-0 flex-1 rounded-lg border bg-card px-2 text-base"
          value={items[index]?.id ?? ""}
          disabled={disabled}
          onChange={(event) => onSelect(event.target.value)}
        >
          {items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.type === "instruction"
                ? t({ zh: "题目说明", en: "Instructions" })
                : t({ zh: `第 ${++number} 题`, en: `Question ${number}` })}
            </option>
          ))}
        </select>
        <Button
          variant="outline"
          className="min-h-11"
          disabled={disabled || index === items.length - 1}
          onClick={() => select(index + 1)}
        >
          {t({ zh: "下一题", en: "Next" })}
        </Button>
      </nav>
      <p className="text-sm text-muted-foreground">
        {disabled
          ? t({
              zh: "请先完成录音或处理待上传的录音，再切换题目。",
              en: "Finish recording or resolve the pending upload before switching items.",
            })
          : t({
              zh: "可自由选题，或在题面左右滑动；返回题目可复听、重练。",
              en: "Choose any item or swipe the prompt left or right. Return to listen and practise again.",
            })}
      </p>
      <div
        onTouchStart={(event) => {
          start.current = null
          if (
            disabled ||
            event.touches.length !== 1 ||
            (event.target as HTMLElement).closest(
              "button,input,textarea,select,audio,a,[contenteditable]",
            )
          )
            return
          start.current = {
            x: event.touches[0].clientX,
            y: event.touches[0].clientY,
          }
        }}
        onTouchCancel={() => {
          start.current = null
        }}
        onTouchEnd={(event) => {
          const origin = start.current
          start.current = null
          if (!origin || !event.changedTouches[0]) return
          const dx = event.changedTouches[0].clientX - origin.x
          const dy = event.changedTouches[0].clientY - origin.y
          if (Math.abs(dx) >= 60 && Math.abs(dx) > Math.abs(dy) * 2)
            select(index + (dx < 0 ? 1 : -1))
        }}
      >
        {children}
      </div>
    </div>
  )
}
