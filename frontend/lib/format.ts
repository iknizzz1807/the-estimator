/** Small formatting + display helpers (numbers always get context in the UI). */

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Math.round(n).toLocaleString("en-US");
}

export function fmtNum(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function fmtPct(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${n.toFixed(digits)}%`;
}

export type DeltaTone = "none" | "neutral" | "warn" | "critical";

/**
 * Delta colour rules from the checklist: |Δ| ≤ 10% neutral, 10–25% orange
 * warning, > 25% red (critical only).
 */
export function deltaTone(deltaPct: number | null | undefined): DeltaTone {
  if (deltaPct === null || deltaPct === undefined || Number.isNaN(deltaPct)) {
    return "none";
  }
  const abs = Math.abs(deltaPct);
  if (abs <= 10) return "neutral";
  if (abs <= 25) return "warn";
  return "critical";
}

export function humanDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
