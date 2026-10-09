import { useI18n } from "@/lib/i18n"

/** IELTS Part 2 话题卡：提示可以谈到的要点。 */
export default function CueCard({ bullets }: { bullets: string[] }) {
  const { t } = useI18n()
  return (
    <div className="rounded-xl border border-dashed border-primary/40 bg-secondary/40 p-4">
      <p className="text-xs font-semibold tracking-wide text-primary">
        {t({
          zh: "话题卡 · 你可以谈到这些要点",
          en: "Cue card · points you can cover",
        })}
      </p>
      <ul className="mt-2 space-y-1 text-sm">
        {bullets.map((bullet) => (
          <li key={bullet} className="flex items-start gap-2">
            <span
              aria-hidden
              className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary/60"
            />
            <span>{bullet}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
