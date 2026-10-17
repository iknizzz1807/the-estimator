import OnboardingWizard from "@/components/OnboardingWizard";

export default function LandingPage() {
  return (
    <div className="space-y-7">
      <header className="pt-2" data-tour="onboarding-header">
        <div className="text-xs font-medium uppercase tracking-[0.15em] text-[var(--primary)]">
          Agent in the Shell · Challenge #2
        </div>
        <h1 className="mt-2 max-w-3xl text-3xl font-semibold tracking-tight leading-tight text-[var(--ink)] sm:text-4xl">
          From RFP to range — a calibrated effort estimate in one pass.
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-[var(--ink-subtle)] sm:text-base">
          Paste a client email and get{" "}
          <span className="font-medium text-[var(--ink)]">
            P10/P50/P90 effort in days
          </span>
          , the 15 project features extracted with evidence quotes, the questions
          worth asking (ranked by impact), and a learning loop that sharpens with
          every finished project. Math estimates — the LLM only reads.
        </p>
      </header>

      {/* Standard Setup Paths & Sample Scenarios */}
      <OnboardingWizard />

      <p className="text-xs text-[var(--ink-tertiary)]">
        Demo data is synthetic and results are illustrative. The interval is a
        range, not a promise — see the limitations in README.
      </p>
    </div>
  );
}
