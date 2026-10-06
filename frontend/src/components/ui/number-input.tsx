import * as React from "react"
import { useEffect, useState } from "react"

import { Input } from "@/components/ui/input"

/**
 * 受控数字输入：修复「删完残留 0、无法顺畅重输」的通病。
 *
 * 病根是 `onChange={Number(e.target.value)}`——清空时 `Number("") === 0`
 * 直接把字段顶成 0。这里内部保留原始字符串：
 * - 空串/中间态不上抛，父级 state 始终保持上一个有效值（提交永远有值）
 * - 失焦时空/非法回填上一个有效值，合法则规范化（如 "07" → "7"）
 * - min/max 透传给原生 spinner 与键盘；范围校验仍由调用方提交时负责（与后端一致）
 */
export function NumberInput({
  value,
  onValueChange,
  onBlur,
  ...props
}: Omit<React.ComponentProps<"input">, "value" | "onChange" | "type"> & {
  value: number
  onValueChange: (value: number) => void
}) {
  const [raw, setRaw] = useState(() => String(value))
  // 外部值变化（编辑切换/表单重置）时同步显示；用户正在输入且数值未变时不打扰
  useEffect(() => {
    setRaw((current) => {
      const parsed = Number(current)
      return current !== "" && Number.isFinite(parsed) && parsed === value
        ? current
        : String(value)
    })
  }, [value])

  return (
    <Input
      {...props}
      type="number"
      value={raw}
      onChange={(e) => {
        const next = e.target.value
        setRaw(next)
        const parsed = Number(next)
        if (next.trim() !== "" && Number.isFinite(parsed)) {
          onValueChange(parsed)
        }
      }}
      onBlur={(e) => {
        const parsed = Number(e.target.value)
        setRaw(
          e.target.value.trim() === "" || !Number.isFinite(parsed)
            ? String(value)
            : String(parsed),
        )
        onBlur?.(e)
      }}
    />
  )
}
