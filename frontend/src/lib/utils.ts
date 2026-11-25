import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 空值数值展示：null/undefined → 「–」，不把空值折算成 0；数字原样转字符串。 */
export function formatNullableCount(value?: number | null): string {
  return value === null || value === undefined ? "–" : String(value)
}
