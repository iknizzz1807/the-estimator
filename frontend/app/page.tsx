import OnboardingWizard from "@/components/OnboardingWizard";

export default function LandingPage() {
  return (
    <div className="space-y-6">
      <header className="pt-2">
        <div className="num text-[11px] uppercase tracking-[0.3em] text-[var(--cyan)]">
          Agent in the Shell · Challenge #2
        </div>
        <h1 className="mt-2 max-w-3xl text-3xl font-semibold leading-tight text-[var(--text)]">
          From RFP to range — a calibrated effort estimate in one pass.
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--dim)]">
          Paste a client email and get{" "}
          <span className="text-[var(--text)]">
            P10/P50/P90 effort in days
          </span>
          , the 15 project features extracted with evidence quotes, the questions
          worth asking (ranked by impact), and a learning loop that sharpens with
          every finished project. Math estimates — the LLM only reads.
        </p>
      </header>

      <OnboardingWizard />

      <p className="text-xs text-[var(--faint)]">
        Demo data is synthetic and results are illustrative. The interval is a
        range, not a promise — see the limitations in README.
      </p>
    </div>
  );
}
