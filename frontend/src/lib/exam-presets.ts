import type { ExamItemSettings } from "@/client"

export type ExamPresetId =
  | "class-reading"
  | "listen-repeat"
  | "ielts-part2"
  | "toefl-repeat"

export const EXAM_PRESETS: Record<
  ExamPresetId,
  {
    wait_seconds: number
    after_audio_seconds: number
    prep_seconds: number | null
  }
> = {
  "class-reading": {
    wait_seconds: 3,
    after_audio_seconds: 1,
    prep_seconds: null,
  },
  "listen-repeat": {
    wait_seconds: 2,
    after_audio_seconds: 2,
    prep_seconds: null,
  },
  "ielts-part2": {
    wait_seconds: 3,
    after_audio_seconds: 2,
    prep_seconds: 60,
  },
  "toefl-repeat": {
    wait_seconds: 2,
    after_audio_seconds: 2,
    prep_seconds: null,
  },
}

const PRESETS_FOR_TYPE: Record<string, ExamPresetId[]> = {
  passage: ["class-reading"],
  repeat: ["listen-repeat", "toefl-repeat"],
  question: ["ielts-part2"],
  instruction: ["class-reading"],
}

export function examPresetsFor(
  itemType: string,
): { id: ExamPresetId; settings: (typeof EXAM_PRESETS)[ExamPresetId] }[] {
  return (PRESETS_FOR_TYPE[itemType] ?? []).map((id) => ({
    id,
    settings: EXAM_PRESETS[id],
  }))
}

export function applyExamPreset(
  current: ExamItemSettings,
  preset: (typeof EXAM_PRESETS)[ExamPresetId],
): ExamItemSettings {
  return {
    ...current,
    wait_seconds: preset.wait_seconds,
    after_audio_seconds: preset.after_audio_seconds,
    prep_seconds: preset.prep_seconds,
  }
}
