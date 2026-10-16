/** Session-storage handoff between onboarding and the estimate screen. */

import type { EstimateResponse } from "./types";

const ESTIMATE_KEY = "estimator:lastEstimate";
const PREFILL_KEY = "estimator:prefillEmail";

export interface StoredEstimate {
  estimate: EstimateResponse;
  scenarioTitle?: string;
}

export function storeEstimate(payload: StoredEstimate): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(ESTIMATE_KEY, JSON.stringify(payload));
  } catch {
    // storage full/unavailable — ignore, the estimate page re-runs on demand
  }
}

export function readStoredEstimate(): StoredEstimate | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(ESTIMATE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredEstimate;
  } catch {
    return null;
  }
}

export function storePrefillEmail(email: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(PREFILL_KEY, email);
  } catch {
    // ignore
  }
}

export function readPrefillEmail(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(PREFILL_KEY);
}
