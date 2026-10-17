import type { ReactNode } from "react";

/*
 * Linear-inspired UI primitives.
 * Surface ladder: canvas (#010102), surface-1 (#0f1011), surface-2 (#141516), surface-3 (#18191a)
 * Hairline borders: hairline (#23252a), hairline-strong (#34343a)
 * Text hierarchy: ink (#f7f8f8), ink-muted (#d0d6e0), ink-subtle (#8a8f98), ink-tertiary (#62666d)
 * Brand accent: primary (#5e6ad2), hover (#828fff)
 */

export function Panel({
  title,
  subtitle,
  right,
  children,
  className = "",
  id,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`panel p-4 sm:p-5 ${className}`}>
      {(title || right) && (
        <header className="mb-3.5 flex flex-wrap items-start justify-between gap-2 border-b border-[var(--hairline)]/40 pb-2.5">
          <div>
            {title && (
              <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--ink-subtle)]">
                {title}
              </h2>
            )}
            {subtitle && (
              <p className="mt-0.5 text-xs text-[var(--ink-tertiary)]">{subtitle}</p>
            )}
          </div>
          {right && <div className="flex items-center gap-2">{right}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

const TONE_CLASS: Record<string, string> = {
  neutral: "",
  ok: "chip-ok",
  off: "chip-off",
  unknown: "chip-unknown",
  info: "chip-info",
};

export function Chip({
  tone = "neutral",
  children,
  title,
}: {
  tone?: "neutral" | "ok" | "off" | "unknown" | "info";
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`chip ${TONE_CLASS[tone]}`} title={title}>
      {children}
    </span>
  );
}

export function StatCard({
  label,
  value,
  unit,
  sub,
  tone = "default",
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: string;
  sub?: ReactNode;
  tone?: "default" | "cyan" | "lime" | "amber" | "dim";
}) {
  const valueColor: Record<string, string> = {
    default: "text-[var(--ink)]",
    cyan: "text-[var(--primary-hover)]",
    lime: "text-[var(--success)]",
    amber: "text-[var(--warning)]",
    dim: "text-[var(--ink-muted)]",
  };
  return (
    <div className="panel-2 p-3.5 sm:p-4">
      <div className="text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
        {label}
      </div>
      <div className={`num mt-1.5 text-2xl font-semibold tracking-tight tabular-nums ${valueColor[tone]}`}>
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-[var(--ink-subtle)]">{unit}</span>}
      </div>
      {sub && <div className="mt-1 text-xs text-[var(--ink-tertiary)]">{sub}</div>}
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={`inline-block animate-spin rounded-full border-2 border-[var(--hairline-strong)] border-t-[var(--primary)] ${className}`}
    />
  );
}

export function ErrorState({
  title = "Could not load data",
  message,
  onRetry,
  hint,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  hint?: string;
}) {
  return (
    <div className="banner banner-red flex-col items-start gap-1.5" role="alert">
      <div className="text-xs font-semibold text-[#fecdd3]">{title}</div>
      <div className="num text-xs text-[var(--ink-muted)]">{message}</div>
      {hint && <div className="text-xs text-[var(--ink-subtle)]">{hint}</div>}
      {onRetry && (
        <button type="button" className="btn btn-secondary mt-1 px-2.5 py-1 text-xs" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-[var(--hairline-strong)] bg-[var(--surface-1)]/40 px-6 py-8 text-center">
      <div className="text-sm font-medium text-[var(--ink-muted)]">{title}</div>
      {hint && <div className="max-w-md text-xs text-[var(--ink-tertiary)]">{hint}</div>}
      {children}
    </div>
  );
}

export function ConfidenceBar({ value }: { value: number | null }) {
  if (value === null || value === undefined) return null;
  const pct = Math.round(value * 100);
  const color =
    pct >= 75 ? "bg-[var(--success)]" : pct >= 45 ? "bg-[var(--primary)]" : "bg-[var(--warning)]";
  return (
    <div className="flex items-center gap-2" title={`Extraction confidence ${pct}%`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full border border-[var(--hairline)] bg-[var(--surface-3)]">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="num text-[11px] tabular-nums text-[var(--ink-subtle)]">{pct}%</span>
    </div>
  );
}

export function SkeletonLines({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2.5" aria-hidden>
      {Array.from({ length: lines }).map((_, index) => (
        <div
          key={index}
          className="skeleton h-4 rounded-md"
          style={{ width: `${100 - index * 12}%` }}
        />
      ))}
    </div>
  );
}
