import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

const CUSTOM = "__custom__"

/**
 * 主题选择器：优先从已有主题列表选（`GET /admin/topics`），
 * 需要新主题时切换为手输，避免各处自由输入导致主题碎片化。
 */
export function TopicPicker({
  value,
  onChange,
  topics,
  disabled = false,
  placeholder = "选择主题",
}: {
  value: string
  onChange: (next: string) => void
  topics: string[]
  disabled?: boolean
  placeholder?: string
}) {
  const [custom, setCustom] = useState(false)

  useEffect(() => {
    // 编辑时值不在列表里（历史数据）→ 自动进手输态，保证能回显
    if (value && topics.length > 0 && !topics.includes(value)) {
      setCustom(true)
    }
  }, [value, topics])

  if (custom) {
    return (
      <div className="flex gap-2">
        <Input
          value={value}
          disabled={disabled}
          placeholder="输入新主题"
          onChange={(e) => onChange(e.target.value)}
        />
        {topics.length > 0 && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setCustom(false)
              onChange(topics[0])
            }}
          >
            用列表
          </Button>
        )}
      </div>
    )
  }

  return (
    <Select
      value={value || undefined}
      disabled={disabled}
      onValueChange={(next) => {
        if (next === CUSTOM) {
          setCustom(true)
          onChange("")
          return
        }
        onChange(next)
      }}
    >
      <SelectTrigger className="w-full">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {topics.map((topic) => (
          <SelectItem key={topic} value={topic}>
            {topic}
          </SelectItem>
        ))}
        <SelectItem value={CUSTOM}>＋ 自定义主题…</SelectItem>
      </SelectContent>
    </Select>
  )
}
