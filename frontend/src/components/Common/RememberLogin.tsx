import { useId } from "react"

import { Checkbox } from "@/components/ui/checkbox"
import { useI18n } from "@/lib/i18n"

/**
 * 「7 天内免登录」勾选项（学生 / 教师 / 学校入口三处共用）。
 *
 * 默认会话 24 小时——机房、共用平板上学生离座后最迟一天失效；
 * 勾选后才签发 7 天 token（个人设备）。副标题写清公用电脑不要勾。
 */
export function RememberLogin({
  checked,
  onCheckedChange,
  disabled,
  testId,
}: {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled: boolean
  testId?: string
}) {
  const { t } = useI18n()
  const id = useId()
  return (
    <div className="flex items-start gap-3">
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={(value) => onCheckedChange(value === true)}
        disabled={disabled}
        data-testid={testId}
        className="mt-1"
      />
      <label htmlFor={id} className="cursor-pointer text-sm leading-6">
        {t({ zh: "7 天内免登录", en: "Keep me signed in for 7 days" })}
        <span className="block text-xs leading-5 text-muted-foreground">
          {t({
            zh: "公用电脑请不要勾选；默认登录状态 24 小时后失效。",
            en: "Don't tick this on a shared computer — sessions expire after 24 hours by default.",
          })}
        </span>
      </label>
    </div>
  )
}
