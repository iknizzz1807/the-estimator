import type { ReactNode } from "react";

/* Small hand-rolled primitives (no shadcn/ui — keeps deps lean). */

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
        <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            {title && (
              <h2 className="text-[13px] font-semibold uppercase tracking-[0.12em] text-[var(--dim)]">
                {title}
              </h2>
            )}
            {subtitle && (
              <p className="mt-0.5 text-xs text-[var(--faint)]">{subtitle}</p>
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
    default: "text-[var(--text)]",
    cyan: "text-[var(--cyan)]",
    lime: "text-[var(--lime)]",
    amber: "text-[var(--amber)]",
    dim: "text-[var(--dim)]",
  };
  return (
    <div className="panel-2 p-3">
      <div className="text-[11px] uppercase tracking-[0.1em] text-[var(--dim)]">
        {label}
      </div>
      <div className={`num mt-1 text-2xl font-semibold ${valueColor[tone]}`}>
        {value}
        {unit && <span className="ml-1 text-sm text-[var(--dim)]">{unit}</span>}
      </div>
      {sub && <div className="mt-1 text-xs text-[var(--faint)]">{sub}</div>}
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={`inline-block animate-spin rounded-full border-2 border-[var(--border-strong)] border-t-[var(--cyan)] ${className}`}
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
    <div className="banner banner-red flex-col items-start" role="alert">
      <div className="font-medium">{title}</div>
      <div className="num text-xs">{message}</div>
      {hint && <div className="text-xs opacity-80">{hint}</div>}
      {onRetry && (
        <button type="button" className="btn mt-1" onClick={onRetry}>
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
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-[var(--border)] px-6 py-8 text-center">
      <div className="text-sm font-medium text-[var(--dim)]">{title}</div>
      {hint && <div className="max-w-md text-xs text-[var(--faint)]">{hint}</div>}
      {children}
    </div>
  );
}

export function ConfidenceBar({ value }: { value: number | null }) {
  if (value === null || value === undefined) return null;
  const pct = Math.round(value * 100);
  const color =
    pct >= 75 ? "bg-[var(--lime)]" : pct >= 45 ? "bg-[var(--cyan)]" : "bg-[var(--amber)]";
  return (
    <div className="flex items-center gap-2" title={`Extraction confidence ${pct}%`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-[#1a2637]">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="num text-[11px] text-[var(--dim)]">{pct}%</span>
    </div>
  );
}

export function SkeletonLines({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: lines }).map((_, index) => (
        <div
          key={index}
          className="skeleton h-4"
          style={{ width: `${100 - index * 12}%` }}
        />
      ))}
    </div>
  );
}
