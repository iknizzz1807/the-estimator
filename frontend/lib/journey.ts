/**
 * Interactive Evaluation Journey State & Dispatcher.
 * Coordinates 1-click execution across routes, tracks progress in localStorage,
 * and enables both HUD and Bento components.
 */

export interface JourneyMilestone {
  id: "scenario_stream" | "voi_shrink" | "codebase_friction" | "proof_replay";
  number: string;
  title: string;
  tagline: string;
  description: string;
  ahaMoment: string;
  keyMetric: string;
  targetRoute: string;
  actionLabel: string;
}

export const JOURNEY_MILESTONES: JourneyMilestone[] = [
  {
    id: "scenario_stream",
    number: "01",
    title: "Intake & RFP Normalization",
    tagline: "LLM reads and extracts with verbatim evidence quotes",
    description: "Extract 15 binary complexity features from messy RFP text with exact quotes and confidence scoring. Missing items stay unknown — never guessed.",
    ahaMoment: "LLM extraction has 100% negation accuracy; zero effort numbers are guessed by the LLM.",
    keyMetric: "F1 0.933 · 15 features",
    targetRoute: "/estimate",
    actionLabel: "Run Scenario A (Fintech)",
  },
  {
    id: "voi_shrink",
    number: "02",
    title: "Uncertainty & Live Range Shrink",
    tagline: "Ridge regression + Conformal prediction + Monte Carlo",
    description: "Missing information widens the interval honestly via Monte Carlo. Clarifying questions are ranked by Value of Information (days at stake). Answering them shrinks the range live.",
    ahaMoment: "Answering Yes/No shrinks [P10, P90] in real time without touching the database.",
    keyMetric: "Coverage 86.7% · Relative spread −30%",
    targetRoute: "/estimate",
    actionLabel: "Simulate VoI Shrink",
  },
  {
    id: "codebase_friction",
    number: "03",
    title: "Codebase Lab Reality Grounding",
    tagline: "Structural friction & similar past changes (29k commits)",
    description: "Same RFP, two codebases = two different quotes. Analyzes AST cyclomatic complexity, churn, fan-in, and past similar commits to apply an auditable risk surcharge.",
    ahaMoment: "Spaghetti repo pushes P50 up and stretches P90; one-directional surcharge only (never discounts).",
    keyMetric: "Friction 0.21 vs 0.69 · Surcharge +15%",
    targetRoute: "/estimate",
    actionLabel: "Attach Spaghetti Repo (Demo B)",
  },
  {
    id: "proof_replay",
    number: "04",
    title: "Empirical Proof & Drift Adaptation",
    tagline: "Walk-forward replay over 218 projects + A/B variance probe",
    description: "Walk-forward replay trains on every prefix of history. Proves the model adapts after a +22% mid-history productivity drift while human team estimates lag.",
    ahaMoment: "System MAE 17.36d vs Team 32.93d; Post-drift System 31.05d vs Team 52.90d.",
    keyMetric: "MAE 17.36d vs 32.93d · 218 steps",
    targetRoute: "/proof",
    actionLabel: "Run Walk-Forward Replay",
  },
];

const STORAGE_KEY = "estimator:journey:v1";
const PENDING_ACTION_KEY = "estimator:pendingJourneyAction";

export interface JourneyState {
  completed: Record<string, boolean>;
  activeStepIndex: number;
}

const DEFAULT_STATE: JourneyState = {
  completed: {},
  activeStepIndex: 0,
};

export function getJourneyState(): JourneyState {
  if (typeof window === "undefined") return DEFAULT_STATE;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_STATE;
    const parsed = JSON.parse(raw) as Partial<JourneyState>;
    return {
      completed: parsed.completed ?? {},
      activeStepIndex: typeof parsed.activeStepIndex === "number" ? parsed.activeStepIndex : 0,
    };
  } catch {
    return DEFAULT_STATE;
  }
}

export function saveJourneyState(state: JourneyState): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    window.dispatchEvent(new CustomEvent("estimator:journey-state-changed", { detail: state }));
  } catch {
    // Ignore storage quota errors
  }
}

export function markStepComplete(stepId: JourneyMilestone["id"]): void {
  const current = getJourneyState();
  if (current.completed[stepId]) return;
  
  const completed = { ...current.completed, [stepId]: true };
  const nextIndex = JOURNEY_MILESTONES.findIndex((m) => !completed[m.id]);
  
  saveJourneyState({
    completed,
    activeStepIndex: nextIndex >= 0 ? nextIndex : JOURNEY_MILESTONES.length - 1,
  });
}

export function resetJourney(): void {
  saveJourneyState(DEFAULT_STATE);
}

export function queueJourneyAction(action: {
  type: JourneyMilestone["id"];
  payload?: unknown;
}): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(PENDING_ACTION_KEY, JSON.stringify(action));
  } catch {
    // Ignore
  }
}

export function popPendingJourneyAction(): {
  type: JourneyMilestone["id"];
  payload?: unknown;
} | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(PENDING_ACTION_KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(PENDING_ACTION_KEY);
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
