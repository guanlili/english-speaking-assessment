import type { ReactNode } from "react"

export function TeachingPageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string
  title: string
  description: string
  actions?: ReactNode
}) {
  return (
    <header className="relative overflow-hidden rounded-2xl bg-primary px-5 py-6 text-primary-foreground sm:px-8 sm:py-8">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-12 -top-20 size-64 rounded-full border border-white/10"
      />
      <div className="relative flex flex-wrap items-center justify-between gap-5">
        <div className="min-w-0 max-w-2xl">
          <p className="mb-3 text-xs font-semibold tracking-widest text-primary-foreground/70">
            {eyebrow}
          </p>
          <h1 className="break-words text-2xl font-bold tracking-tight sm:text-3xl">
            {title}
          </h1>
          <p className="mt-3 text-sm leading-6 text-primary-foreground/80">
            {description}
          </p>
        </div>
        {actions && (
          <div className="flex flex-wrap gap-2 [&_button]:min-h-11 [&_a]:min-h-11">
            {actions}
          </div>
        )}
      </div>
    </header>
  )
}
