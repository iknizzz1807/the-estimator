# BRIEF v4 — add data flywheel + codebase-as-feature, fix contract example

## What changes
1. **Remove these three bottom takeaway lines** (AI-slop tone):
   - Slide 3 (`02 · WHY NOT LLM-ONLY`): `The problem is not randomness. It is calibration.`
   - Slide 4 (`03 · THE FIRST DECISION`): `The LLM is a reader, not an estimator.`
   - Slide 5 (`04 · THE SPLIT`): `The LLM is not allowed to do arithmetic.`
   Keep the slides themselves; just remove the bottom takeaway. Keep the trade-off line on slide 4 (`Audit vs speed...`).

2. **Add two slides** (deck becomes 23 slides):
   - **Data flywheel** after the learning loop.
   - **Codebase as a model feature** after Codebase Lab.

3. **Fix the contract example**: it currently has four `1`s and one `?`. Add one `0` so the table shows all three states. Use `multi_currency = 0` with the quote `"no multi-currency for now"`. Add that line to the email mock so the 0 is grounded. Change the table corner label from `Scenario A` to `Example extraction` to avoid claiming it is the exact scenario vector.

## New slide A — The data flywheel
Position: after `11 · THE LEARNING LOOP`, before `12 · CODEBASE LAB`.

- Kicker: `12 · THE DATA FLYWHEEL`
- Headline: `More history, lower error.`
- Visual: `\FigFlywheel`
  - A circular loop: `project → actual → training row → better model → better range` (and back).
  - Center: `company data`.
  - A small two-bar chart: `60 projects: 23.50 MAE` → `240 projects: 17.36 MAE`; label `same model, more history`.
- Bottom takeaway: `More projects → lower error. The moat is the company's own data.`
- This is the "càng dùng càng có nhiều data công ty, hệ thống càng tốt hơn" slide.

## New slide B — Codebase as a model feature
Position: after `13 · CODEBASE LAB`, before `14 · VIBE CODING — THE LOOP`.

- Kicker: `14 · FROM SURCHARGE TO FEATURE`
- Headline: `When the data exists, the codebase becomes a feature.`
- Visual: `\FigCodebaseFeature`
  - Today: `repo signals → post-hoc surcharge` — `+35% demo-assumed`, `one-directional`, `no learned weight`.
  - With data: `(repo signals, actual_days)` pairs → `columns in the Ridge matrix` — `churn`, `fan-in`, `complexity`, `coverage`, `invasiveness` — `learned coefficient + conformal interval`.
  - A small matrix visual: rows `P001…P240`, columns `15 features` + `5 repo signals`, repo columns highlighted; an arrow from the left panel to the right panel.
- Bottom takeaway: `Instrument the pairs now; the model learns the weight.`
- This is the "codebase becomes features in the linear model instead of a post-hoc add-on" slide. Make the `Today` vs `With data` contrast visually obvious.

## Renumbering (23 slides)
1 Cover
2 01 The problem
3 02 Why not LLM-only
4 03 The first decision
5 04 The split
6 05 The contract
7 06 The output
8 07 Model choice
9 08 Missing data
10 09 The questions
11 10 The quote
12 11 The learning loop
13 **12 The data flywheel** (new)
14 13 Codebase Lab
15 **14 From surcharge to feature** (new)
16 15 Vibe coding — the loop
17 16 The tool stack
18 17 The constraint
19 18 One loop, end to end
20 19 Review checklist
21 20 Scope & guardrails
22 21 Proof
23 22 Why Anduin + close

Page numbers 01–23.

## Figure changes
- Add `\FigFlywheel`.
- Add `\FigCodebaseFeature`.
- Update `\FigProblem`: add a line `No multi-currency for now.` to the email mock.
- Update `\FigContract`: 6 rows (payment_gateway 1, pci_dss 1, mobile_app 1, realtime_ui 1, multi_currency 0, data_migration ?), quote `"no multi-currency for now"` for the 0 row; change the corner label to `Example extraction`.
- Keep all other figures.

## Rules
- Remove the three listed bottom takeaways only; do not remove other takeaway lines.
- No speaker notes.
- Footer stays hairline + page number only.
- White background, 16:9, 0.7 cm safe margin.
- The new slides must be self-explanatory with concrete labels and numbers.
