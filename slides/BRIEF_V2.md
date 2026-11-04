# BRIEF v2 — The Estimator deck (redo)

## What went wrong in v1
The v1 slides were too abstract: a big sentence + a diagram, no example, no narrative.
A viewer who did not hear the speaker could not tell what the product does, what it outputs, or why it matters.
v2 must be **self-explanatory**: every slide carries one concrete example and enough labels to be understood alone.

## The new rule
- White background, 16:9, lots of visuals.
- **Limited text, not zero text.** Aim for ~20–30 words per slide, excluding numbers and short table labels.
- Each slide: kicker + headline + one visual/example + one bottom takeaway.
- No speaker notes. Do not add `\note{}`. Do not produce a notes PDF.
- The deck must tell a story in order: problem → why not LLM → split → contract → output → questions → packages → learning → codebase → vibe coding → worked example → proof → fit.

## Exact slide plan (14 slides)

### 1. Cover
- Wordmark: `THE ESTIMATOR`
- Sub: `From a client email to a range you can defend.`
- Small: `Nguyen My Thong · Anduin Cybernetics`
- Figure: envelope → 15 feature chips → P10/P50/P90 range bar. Reuse the v1 cover.

### 2. The problem
- Kicker: `01 · THE PROBLEM`
- Headline: `A client email. One number. No evidence.`
- Visual: a mock email card (left) with a highlighted excerpt:
  `"We need a payments product... mobile app for iOS and Android... PCI-DSS certification..."` 
  A sticky note on the right: `How many days?` with a big `?`.
  Three small labels under the email: `2 hours reading` · `3 clarifying questions` · `still a guess`.
- Bottom takeaway: `The team's own estimates miss by 33 days on average.`
- This is the hook; it must look like a real RFP, not an abstract card.

### 3. Why not just ask the LLM
- Kicker: `02 · WHY NOT LLM-ONLY`
- Headline: `The LLM gives an answer. Not a defensible one.`
- Visual: a two-column comparison.
  - Left, red: `LLM-only` → big `258` → label `days MAE` → small `last 42 projects`.
  - Right, teal: `The Estimator` → big `19` → label `days MAE` → small `same 42 projects`.
  - Below: 4 small failure chips: `no history` · `no calibration` · `no evidence` · `missing info = guess`.
- Bottom takeaway: `The problem is not randomness. It is calibration.`
- Note for the speaker (not on slide): at temperature 0 the LLM is deterministic; it confuses calendar time with person-days.

### 4. The split
- Kicker: `03 · THE SPLIT`
- Headline: `So we split the job in two.`
- Visual: pipeline with a clear boundary line.
  - Row: `email` → `LLM` → `15 features + quotes` ┃ `Ridge + conformal + MC` → `P10 / P50 / P90`.
  - A vertical dashed boundary between `15 features` and the math, labelled `LLM stops here`.
  - Two labels under the rows: `language → structure` (teal) and `structure → range` (navy).
- Bottom takeaway: `The LLM is not allowed to do arithmetic.`

### 5. The contract (with a real example)
- Kicker: `04 · THE CONTRACT`
- Headline: `15 features. 3 states. A quote for each.`
- Visual: a compact example table (5 rows) from Scenario A:
  | feature | value | evidence from the email |
  |---|---|---|
  | payment_gateway | 1 | "process payments through Stripe" |
  | pci_dss | 1 | "requires PCI-DSS certification" |
  | mobile_app | 1 | "mobile app for iOS and Android" |
  | realtime_ui | 1 | "live updates on a dashboard" |
  | data_migration | ? | not mentioned |
- Legend: `1 present` · `0 absent` · `? unknown`.
- Bottom takeaway: `A null is not a zero. It means "the email didn't say".`
- This slide must be readable on its own. The table is the point.

### 6. The output
- Kicker: `05 · THE OUTPUT`
- Headline: `A range, not a point.`
- Visual: large horizontal range bar with `79` (P10), `111` (P50), `191` (P90).
  - Callout left: `10 features unknown` → arrow to the wide bar.
  - Small label: `Example: Scenario A, offline run`.
  - Under the bar: `P10` · `P50` · `P90` and `days`.
- Bottom takeaway: `The width is information: it shows what we don't know.`

### 7. The questions (with a real example)
- Kicker: `06 · THE QUESTIONS`
- Headline: `Ask what actually moves the number.`
- Visual: a ranked list of 5 bars:
  `data_migration +63.8` · `legacy_tech_stack +56.0` · `multi_tenancy +42.0` · `privacy_compliance +36.4` · `external_data_sync +32.3`.
  Top question text (short): `Migrate data from legacy systems?`
  A small before/after:
  - `Before: 79–111–191`
  - `Answer "No": 78–108–168` (teal, narrower)
  - `Answer "Yes": 127–175–274` (amber, wider)
- Bottom takeaway: `Answers add information. They don't always shrink the range.`
- This is a nuanced, credible point; keep it.

### 8. The packages
- Kicker: `07 · THE QUOTE`
- Headline: `A budget turns the range into a decision.`
- Visual: three cards, a horizontal budget line at `100 days`:
  - `Essential` · P50 `95` · over-budget `46%` · drops `mobile_app, realtime_ui`
  - `Standard` · P50 `119` · over-budget `63%` · drops `mobile_app`
  - `Full` · P50 `207` · over-budget `91%` · nothing dropped
  - Recommendation chip: `Essential` + `renegotiate budget or timeline`.
- Bottom takeaway: `At 100 days, every scope is over budget. The product says so.`
- Keep the labels short.

### 9. The learning loop
- Kicker: `08 · THE LEARNING LOOP`
- Headline: `Every finished project moves the model.`
- Visual: left: `Predicted 111` vs `Actual 180`; right: a small coefficient table:
  `payment_gateway 1.49 → 1.51` · `mobile_app 1.74 → 1.76` · `pci_dss 1.50 → 1.52`.
  Below: a small drift chart / line: `after drift: system 31.05 vs team 52.90` (last 10 projects).
- Bottom takeaway: `The model updates after one project. The team's intuition does not.`

### 10. Codebase Lab
- Kicker: `09 · CODEBASE LAB`
- Headline: `The same request costs more in a messy repo.`
- Visual: three stages:
  1. repo tree (`pallets/flask`)
  2. signal chips: `churn` · `fan-in` · `complexity` · `coverage` · `authors` + `similar changes`
  3. friction gauge: `0.66 medium`
  - A bottom row: `base P50 207` → `adjusted P50 280` (`+35%`) with a one-way arrow `widen risk, never discount`.
  - Small tag: `29,059 real commits · Python only`.
- Bottom takeaway: `A clean repo never gets a discount. Under-quoting is the expensive error.`

### 11. Vibe coding process
- Kicker: `10 · THE PROCESS`
- Headline: `Vibe coding, with a seatbelt.`
- Visual: the 7-step loop: `decide → constrain → generate → review → test → measure → document`.
  - AI column: `DeepSeek` · `code assistant` · `eval scripts`.
  - Human column: `decide` · `review` · `gatekeep`.
  - Phone icon + `built on a phone`.
- Bottom takeaway: `The smallest process that makes the next change safe.`

### 12. Vibe coding worked example
- Kicker: `11 · ONE LOOP, END TO END`
- Headline: `The AI wrote plausible code. The review made it right.`
- Visual: a 5-step horizontal timeline with short labels and numbers:
  1. `Ask` — `handle unknown features without guessing`
  2. `Generate` — `first version samples unknowns at 25%`
  3. `Review` — `why 25%? a null means "not mentioned"`
  4. `Measure` — `49.64 MAE vs zero-fill 21.34`
  5. `Fix` — `P(present | null) = 4.1% → 20.48 MAE`
- Bottom takeaway: `The valuable step was not generation. It was the question I asked next.`
- This is the most important slide for the Anduin interview. Make it visual and concrete.

### 13. Proof
- Kicker: `12 · PROOF`
- Headline: `The numbers, with the caveats.`
- Visual: dashboard with 4 big cards:
  - `17.36` MAE vs team 32.93
  - `86.7%` coverage (189/218)
  - `0.933` extraction F1
  - `$0.20` / 240 emails
  - A second row: `242 offline tests` · `31 decisions` · `20.48 MAE end-to-end`
- Bottom caveat: `Synthetic corpus · demo-assumed codebase coefficients · no auth yet.`
- Keep the caveat visible.

### 14. Fit + close
- Kicker: `13 · WHY ANDUIN`
- Headline: `Business builds. Someone has to make it trustworthy.`
- Visual: a bridge: `Business` → `Technical anchor` → `Production`.
  - Under it: 3 chips `map` → `prototype` → `harden`.
  - A small mapping table (2 columns, 4 rows):
    `messy email → structured features`
    `deterministic math → auditable number`
    `questions → human review`
    `actuals → learning loop`
- Bottom: the quote `I don't use AI to skip thinking. I use it to think faster — then I test harder.` + `Thank you.`
- The quote is the close; keep it large but not the whole slide.

## Figure macro interface (v2)
Create `slides/figures.tex` (overwrite v1) with these macros, each a self-contained `tikzpicture` on a 14.6 x 7.2 cm canvas:

```latex
\newcommand{\FigCover}{...}       % reuse/adapt v1
\newcommand{\FigProblem}{...}     % email card + "How many days?" sticky note
\newcommand{\FigLLMFail}{...}     % 258 vs 19 bars + 4 failure chips
\newcommand{\FigSplit}{...}       % pipeline with boundary
\newcommand{\FigContract}{...}    % 5-row example table + legend
\newcommand{\FigRange}{...}       % 79/111/191 range bar
\newcommand{\FigQuestions}{...}   % ranked bars + before/after
\newcommand{\FigPackages}{...}    % 3 cards + budget line
\newcommand{\FigLearning}{...}    % predicted vs actual + coefficient table + drift
\newcommand{\FigCodebase}{...}    % Flask tree -> signals -> gauge + 207 -> 280
\newcommand{\FigLoop}{...}        % reuse/adapt v1 loop
\newcommand{\FigWorked}{...}      % 5-step timeline
\newcommand{\FigProof}{...}       % reuse/adapt v1 dashboard
\newcommand{\FigBridge}{...}      % reuse/adapt v1 bridge + mapping table
\newcommand{\FigClose}{...}       % minimal range bar
```

Rules:
- Assume colors `ink, teal, teallight, amber, amberlight, red, redlight, blue, graytext, lightsurface, hairline`.
- No fontawesome, no external images.
- Text on figures: short labels, but enough to understand the example. Max ~6 words per label; numbers allowed.
- Make tables look like clean cards, not LaTeX `tabular` with grid lines. Use rounded rows and alignment.
- Keep the same visual language as v1: white, rounded cards, thin hairlines, teal/amber/red accents.

## Deck layout rules
- `\documentclass[aspectratio=169,10pt]{beamer}`, lmodern sans, white background.
- Kicker top-left, headline 22–26pt navy bold, figure below, bottom takeaway 9–10pt gray.
- No bullet lists. Use cards, chips, bars, tables.
- Keep a 0.7 cm safe margin.
- Each slide should make sense without narration.

## Source of truth for numbers
- Scenario A offline run: 79 / 111 / 191; 10 unknowns.
- Answer data_migration=0: 78 / 108 / 168.
- Answer data_migration=1: 127 / 175 / 274.
- Top question impacts: 63.8, 56.0, 42.0, 36.4, 32.3.
- Packages at ~100 days: Essential 95 / 46%, Standard 119 / 63%, Full 207 / 91%.
- Learning: predicted 111, actual 180; payment_gateway 1.49→1.51, mobile_app 1.74→1.76, pci_dss 1.50→1.52; post-drift last 10: system 31.05 vs team 52.90.
- Codebase Flask: friction 0.66 medium; base P50 207 → adjusted 280 (+35%); 29,059 commits.
- LLM-only vs system on last 42: 258 vs 19 MAE.
- Proof: 17.36 MAE vs team 32.93; coverage 86.7% (189/218); extraction F1 0.933; $0.20 for 240 emails; 242 tests; 31 decisions; end-to-end 20.48 MAE / 85.3%.
- 240 projects, 228 done, 218 walk-forward steps; 15 features; 2^15 = 32,768.
- Caveats: synthetic corpus, demo-assumed codebase coefficients, no auth/rate limit.

## Tone
Product review at a fintech: concrete, calm, evidence-first. No hype. No abstract slogans without an example.
