# BRIEF v3 — The Estimator deck (problem-solving + trade-offs, more slides)

## What changes from v2
- **Remove the "The Estimator" text from the footer.** Keep the thin hairline and the page number.
- **More slides** (21 total), more explanation, especially the vibe-coding section.
- Frame every major choice as **Problem → Options → Trade-off → Decision → Evidence**.
- No speaker notes. No `\note{}`.
- White background, 16:9, visuals, but enough text to be understood without narration (~30–50 words per slide, excluding tables/numbers).
- Keep the v2 examples and numbers. Add decision/trade-off slides.

## Slide plan (21 slides)

### 1. Cover
Keep v2 cover: 3 steps (client email → 15 features → calibrated range). No footer brand.

### 2. The problem
Keep v2 slide 2: Nordwind Pay email + "How many days?" + 2 hours / 3 questions / still a guess.
Bottom: `The team's own estimates miss by 33 days on average.`

### 3. Why not LLM-only
Keep v2 slide 3: 258 vs 19 MAE + four failure chips.
Bottom: `The problem is not randomness. It is calibration.`

### 4. The first decision — what should the LLM be allowed to decide?
NEW. Three option cards:
- **A. LLM end-to-end** — `reads + estimates` — `fast, but no audit, no calibration` — red ✗.
- **B. LLM + hand-written rules** — `extract + rules` — `auditable, but brittle, no learning` — amber ~.
- **C. LLM + math** — `extract only; math estimates` — `auditable · calibrated · learns` — teal ✓ `chosen`.
Bottom: `The LLM is a reader, not an estimator.`
Visual: `\FigDecision`.

### 5. The split
Keep v2 slide 4: email → LLM → 15 features ┃ Ridge/conformal/MC → P10/P50/P90.
Bottom: `The LLM is not allowed to do arithmetic.`

### 6. The contract
Keep v2 slide 5: 5-row example table (feature / value / quote) + legend.
Bottom: `A null is not a zero. It means "the email didn't say".`

### 7. The output
Keep v2 slide 6: range 79 / 111 / 191, "10 features unknown", "Scenario A, offline run".
Bottom: `The width is information: it shows what we don't know.`

### 8. Model choice — we tested the alternatives
NEW. A comparison table:
| model | MAE | coverage | explainable | verdict |
|---|---|---|---|---|
| Ridge + conformal ✓ | 17.36 | 86.7% | yes | chosen: stable, inspectable |
| Split conformal | 17.25 | 75.7% | yes | similar MAE, lower coverage |
| Gradient boosting | 25.23 | 72.9% | no | overfits at 228 rows |
| Quantile GBM | 25.56 | 66.5% | no | worse tails |
| Median baseline | 32.76 | 77.1% | n/a | no learning |
Bottom: `At 228 projects, the simpler model wins on trust, not just MAE.`
Visual: `\FigModelChoice`.

### 9. Missing data — the mistake that made it honest
NEW decision version of the v2 worked example:
- Options: `global prior 25.2%` → 49.64 MAE; `zero-fill` → 21.34 MAE; `conditional P(1|null)=4.1%` → 20.48 MAE.
- Highlight the conditional option as chosen.
Bottom: `Measure the mechanism, not just the model.`
Visual: `\FigMissing`.

### 10. The questions
Keep v2 slide 7: ranked impact bars + before/after (No narrows, Yes widens).
Bottom: `Answers add information. They don't always shrink the range.`

### 11. The quote
Keep v2 slide 8: Essential 95 / Standard 119 / Full 207, 100-day budget, recommendation.
Bottom: `At 100 days, every scope is over budget. The product says so.`

### 12. The learning loop
Keep v2 slide 9: predicted 111 vs actual 180, coefficient updates, drift 31.05 vs 52.90.
Bottom: `The model updates after one project. The team's intuition does not.`

### 13. Codebase Lab — measured vs assumed
NEW framing:
- A chain: `repo signals → friction → change size → person-days`.
- Link 1–3 measured on 29,059 real commits; link 4 (`size → person-days`) assumed, no public dataset.
- Flask example: friction 0.66 → base P50 207 → adjusted 280 (+35%).
- Rule: `widen risk, never discount`; Python-only.
Bottom: `Measure what you can. Label what you can't.`
Visual: `\FigCodebaseChain`.

### 14. Vibe coding — the loop
Keep v2 slide 11: 7-step loop + AI/Human columns + phone note.
Bottom: `The smallest process that makes the next change safe.`
Add a second line under the loop: `AI is fast. The human is the gatekeeper.`

### 15. Vibe coding — the tool stack
NEW. Two columns:
- **Used:** `DeepSeek` (extraction) · `code assistant` (boilerplate, tests) · `eval scripts` (measurement) · `git` (history).
- **Deliberately not:** `50 MCP servers` · `10k-line skill files` · `autonomous agent shipping code`.
- A small axis: `ceremony ←→ speed`, marker at `smallest process`.
Bottom: `Every unit of setup overhead is a unit not spent on the problem.`
Visual: `\FigTools`.

### 16. Vibe coding — the constraint
NEW. The laptop-broke story:
- Timeline: `laptop broke` → `Termux + PRoot` → `net cafe for tests` → `shipped`.
- Three labels: `small diffs` · `explicit contracts` · `tests as the safety net`.
Bottom: `The constraint removed the option to be sloppy.`
Visual: `\FigPhone`.

### 17. Vibe coding — one loop, end to end
Keep v2 slide 12: Ask → Generate → Review → Measure → Fix (25% → 4.1% → 20.48).
Bottom: `The valuable step was not generation. It was the question I asked next.`

### 18. Vibe coding — how I review AI code
NEW. A checklist card:
- `Contract`: does it match the interface?
- `Failure modes`: empty, None, huge input?
- `Determinism`: same input → same output?
- `Evidence`: can I trace the number?
- `Tests`: does the test fail if I break it?
- `Rollback`: can I revert in one commit?
Bottom: `If I can't test it, I don't ship it.`
Visual: `\FigReview`.

### 19. Scope & guardrails
NEW. Two columns:
- **Guardrails:** `242 offline tests` · `31 decision entries` · `no artifact → no claim` · `graceful failure`.
- **Deliberately not built:** `auth / rate limit` · `extraction cache` · `multi-language codebase` · `retrieval wiring` — each tagged `not on the critical path` / `next`.
Bottom: `Knowing what not to build is part of the design.`
Visual: `\FigScope`.

### 20. Proof
Keep v2 slide 13: 17.36 / 86.7% / 0.933 / $0.20 + 242 / 31 / 20.48 + caveats.
Bottom: `Synthetic corpus · demo-assumed codebase coefficients · no auth yet.`

### 21. Why Anduin + close
Keep v2 slide 14: bridge + mapping table + map/prototype/harden + closing quote.
Bottom: `I don't use AI to skip thinking. I use it to think faster — then I test harder.`

## New figure macros (add to figures.tex)
Keep all v2 macros. Add:
- `\FigDecision` — 3 option cards (A/B/C) with red/amber/teal verdicts.
- `\FigModelChoice` — comparison table (Ridge / split conformal / GBM / quantile GBM / median) with MAE, coverage, explainable, chosen badge.
- `\FigMissing` — 3 bars (49.64 / 21.34 / 20.48) + `P(1|null)=4.1%` + chosen badge.
- `\FigCodebaseChain` — 4-link chain (repo signals → friction → change size → person-days), measured vs assumed, Flask 207→280.
- `\FigTools` — Used vs Deliberately not columns + ceremony/speed axis.
- `\FigPhone` — timeline broken laptop → phone/Termux → net cafe → shipped + 3 labels.
- `\FigReview` — 6-item checklist card.
- `\FigScope` — 2 columns (guardrails / not built) with tags.
Reuse: `\FigCover`, `\FigProblem`, `\FigLLMFail`, `\FigSplit`, `\FigContract`, `\FigRange`, `\FigQuestions`, `\FigPackages`, `\FigLearning`, `\FigCodebase`, `\FigLoop`, `\FigWorked`, `\FigProof`, `\FigBridge`, `\FigClose`.

## Layout rules
- 16:9, white background, 0.7 cm safe margin.
- Kicker 7.5–8pt teal; headline 22–26pt navy bold; labels 8–10pt; takeaway 9–10pt gray.
- No bullet walls. Use cards, tables, chips, bars, timelines.
- Every slide must make sense without narration.
- Page number only in the footer; **remove the "The Estimator" footer text**.
- No notes, no notes PDF.

## Source of truth for numbers
Same as v2, plus:
- Model comparison: Ridge 17.36 / 86.7% / explainable; split conformal 17.25 / 75.7%; GBM 25.23 / 72.9%; quantile GBM 25.56 / 66.5%; median 32.76 / 77.1%.
- Missing data: 49.64 (global 25.2%), 21.34 (zero-fill), 20.48 (conditional 4.1%).
- Codebase chain: 29,059 commits; 3 measured links; 1 assumed; Flask 0.66 / 207 → 280 (+35%).
- Vibe coding: DeepSeek, code assistant, eval scripts; laptop broke, Termux + PRoot, net cafe; 25% → 4.1% → 20.48.
- Scope: 242 tests, 31 decisions; not built: auth, cache, multi-language, retrieval.
- Everything else as v2.

## Tone
Problem-solving, trade-offs, calm confidence. Show the options considered and why the chosen one is defensible. No hype. No abstract slogans without an example.
