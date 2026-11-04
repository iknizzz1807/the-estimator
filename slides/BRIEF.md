# Brief — The Estimator presentation deck (LaTeX / Beamer)

## Goal
A 12-slide, 16:9 presentation for the Anduin Cybernetics "AI Business Operations Associate" onsite project presentation.

**Design law: white background, very visual, extremely little text.**
The speaker talks; the slide shows. Aim for <= 8 words of body text per slide, plus numbers/labels.
All illustrations must be vector TikZ/pgfplots. No external images, no stock photos, no fontawesome (it failed in this TeX bundle).

## Output
- `slides/figures.tex` — reusable TikZ figure macros (agent A)
- `slides/main.tex` — the deck (agent B)
- `slides/the-estimator-deck.pdf` — compiled output
- Compile with Tectonic:
  `C:\Users\Administrator\AppData\Local\Temp\opencode\tectonic\tectonic.exe -X compile main.tex`
  (Tectonic may print a Fontconfig warning and return exit 1; check that the PDF exists and has 12 pages.)

## Technical setup (must work with Tectonic 0.17)
```latex
\documentclass[aspectratio=169,10pt]{beamer}
\usepackage{lmodern}
\renewcommand{\familydefault}{\sfdefault}
\usepackage[T1]{fontenc}
\usepackage{tikz}
\usetikzlibrary{arrows.meta,positioning,calc,shapes.geometric,backgrounds,fit,decorations.pathreplacing}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\usepackage{tcolorbox}
\usepackage{amsmath,amssymb}
```
- `\usetheme{default}`, `\setbeamertemplate{navigation symbols}{}`
- White background: `\setbeamercolor{background canvas}{bg=white}`
- No bullet lists. No paragraphs. Use cards, chips, arrows, big numbers.
- Footer: page number bottom-right, thin accent line, maybe "The Estimator" bottom-left.
- 16:9 page is 16cm x 9cm. Keep a 0.7cm safe margin. Content area ~14.6cm x 7.6cm.
- Use `\begin{frame}[t,plain]` for full-bleed visual slides.

## Palette (define once in main.tex)
- ink / navy: `0B1F3A`
- teal: `0E9F9F`
- teal light: `D9F2F1`
- amber: `E8A317`
- amber light: `FDF0D5`
- red: `D1495B`
- red light: `F8DDE1`
- blue: `3A6EA5`
- gray text: `6B7280`
- light surface: `F4F6F8`
- hairline: `D9DEE5`

Use `\definecolor{...}{HTML}{...}`.

## Typography
- Sans-serif via lmodern + `\familydefault=\sfdefault`.
- Big statement: 26–34pt, navy, bold, max 8 words.
- Kicker: 9pt, uppercase, letter-spaced, teal/gray.
- Numbers: 40–64pt, navy/teal, bold.
- Labels: 8–10pt, gray.
- No long sentences. If a sentence is needed, it goes in the speaker notes, not on the slide.

## Slide list + exact on-slide text

### 1. Cover
- Big: `THE ESTIMATOR`
- Sub: `from RFP to a range you can defend`
- Small: `Nguyen My Thong · Anduin Cybernetics`
- Figure: envelope -> 15 feature chips -> P10/P50/P90 range bar. Elegant, lots of white space.

### 2. Why
- Kicker: `01 · WHY`
- Big: `A number nobody can defend.`
- Figure: 3-step horizontal flow with simple icons: person (pain I've felt) -> building (real at scale) -> hammer/wrench (build). Arrows. Minimal labels under icons: `pain`, `scale`, `build`.
- Bottom micro-line: `solve a pain I've felt -> check it scales -> build`

### 3. The split
- Kicker: `02 · THE SPLIT`
- Big: `The LLM is not allowed to do arithmetic.`
- Figure: two rows.
  - Top row (red, dashed): `email` -> `LLM` -> `number` with a big red X.
  - Bottom row (teal, solid): `email` -> `LLM` -> `15 features` -> `math` -> `P10 / P50 / P90`.
  - Labels only. This is the core architecture diagram.

### 4. The contract
- Kicker: `03 · THE CONTRACT`
- Big: `15 features. 3 states. 1 quote each.`
- Figure: 5 rows x 3 chips = 15 feature chips, grouped by colour (integration, data, UI, security, context). Each chip shows `1`, `0`, or `?`. Legend: `1 present`, `0 absent`, `? unknown`. A quote bubble on the right: `"verbatim evidence"`.
- Big ghost number `15` in the background (light gray).

### 5. The math
- Kicker: `04 · THE MATH`
- Big: `17.36 vs 32.93`
- Figure: horizontal range bar P10–P90 with a P50 line and a bell curve above. Two small markers/bars: `system` 17.36 (teal), `team` 32.93 (gray/red). Label `coverage 86.7%`.
- Tiny labels: `Ridge`, `conformal`, `Monte Carlo` as three small chips.

### 6. The mistake
- Kicker: `05 · THE MISTAKE`
- Big: `A plausible default was worse than zero.`
- Figure: 3 vertical bars: `49.64` (red, global prior), `21.34` (gray, zero-fill), `20.48` (teal, conditional). Highlight the first with a red tag `worse than zero`. Right side: big `4.1%` in a circle, label `P(present | null)`.
- This is the honesty/rigour slide.

### 7. The codebase
- Kicker: `06 · CONTEXT`
- Big: `Same feature. Different repo. Different job.`
- Figure: repo tree on the left -> 5 signal chips in the middle (churn, fan-in, complexity, coverage, authors) + `similar changes` -> a gauge/shield on the right with a one-way arrow. Label `widen risk, never discount`. Small `Python` tag.

### 8. Vibe coding
- Kicker: `07 · THE PROCESS`
- Big: `Vibe coding, with a seatbelt.`
- Figure: circular 7-node loop: `decide -> constrain -> generate -> review -> test -> measure -> document`. Center: `human in the loop`. Two side columns: `AI` (generate, options) and `Human` (decide, review, gatekeep). A small phone icon with `built on a phone`.
- Bottom micro-line: `smallest process that makes the next change safe`

### 9. Guardrails
- Kicker: `08 · GUARDRAILS`
- Big: `Speed is safe only when it's measured.`
- Figure: 2x2 cards: `242 tests`, `31 decisions`, `evidence`, `graceful failure`. Each with a simple icon (check, book, quote, shield). A banner at the bottom: `no artifact -> no claim`.

### 10. Proof
- Kicker: `09 · PROOF`
- Big: `The numbers, with the caveats.`
- Figure: dashboard with 4 large cards:
  - `17.36` MAE vs team 32.93
  - `86.7%` coverage (189/218)
  - `0.933` extraction F1
  - `$0.20` / 240 emails
- Tiny caveat line: `synthetic corpus · demo-assumed coefficients · no auth yet`
- Maybe a subtle sparkline / line chart in the background.

### 11. Fit
- Kicker: `10 · FIT`
- Big: `Business builds. Someone has to make it trustworthy.`
- Figure: bridge diagram: `Business` on the left, `Production` on the right, `Technical anchor` in the centre. Below: `map -> prototype -> harden`. Small icons: people, bridge, server/shield.

### 12. Close
- Big quote: `I don't use AI to skip thinking. I use it to think faster — then I test harder.`
- Small: `Thank you.`
- Figure: a minimal range bar with P10/P50/P90 and a thin teal line. Lots of white space.

## Figure macro interface (agent A -> agent B)
Create `slides/figures.tex` with these exact macro names, each a self-contained `tikzpicture` that fits a 14.6cm x 7.2cm area:

```latex
\newcommand{\FigCover}{...}
\newcommand{\FigWhy}{...}
\newcommand{\FigSplit}{...}
\newcommand{\FigContract}{...}
\newcommand{\FigRange}{...}
\newcommand{\FigMistake}{...}
\newcommand{\FigCodebase}{...}
\newcommand{\FigLoop}{...}
\newcommand{\FigGuardrails}{...}
\newcommand{\FigProof}{...}
\newcommand{\FigBridge}{...}
\newcommand{\FigClose}{...}
```

Rules:
- Each macro is a complete `tikzpicture` with `[x=1cm,y=1cm]` and coordinates roughly 0..14.6 x 0..7.2.
- No text longer than 3 words per label (numbers allowed).
- Use the palette via `\colorlet` names defined in `main.tex`; `figures.tex` can assume they exist.
- Use `\sffamily`, `\bfseries` for big labels.
- Avoid overfull boxes. Test with a standalone `figures-test.tex` that calls every macro in a frame, compile, and check the log for `Overfull \hbox`.
- Keep line weights consistent: 0.6pt normal, 1.2pt for emphasis, 2pt for hero arrows.
- Rounded corners: `rounded corners=4pt` for cards; `rounded corners=2pt` for chips.
- Add subtle shadows only if they stay light (`drop shadow={opacity=0.08}`); white background must stay clean.

## Quality bar
- Every slide must be readable from the back of a room.
- No slide may have a wall of text.
- No element may cross the safe margin.
- The deck must compile to exactly 12 pages, 16:9, white background.
- The visual language must be consistent across slides: same palette, same corner radius, same arrow style, same label size.

## Speaker notes
Add a short `\note{...}` to each frame (2–4 sentences, English). The main PDF ignores notes; a notes PDF can be produced later. Keep the notes factual: numbers from the project, no new claims.

## Source of truth for numbers
- 240 projects, 228 done, 218 walk-forward steps
- MAE P50: 17.36 days vs team 32.93
- Coverage: 86.7% (189/218)
- Extraction micro-F1: 0.933 (stub 0.845)
- Negation "not X" -> false: 100% (214/214); stub 43.1%
- Last 10 after drift: 31.05 vs team 52.90
- End-to-end null-prior: 20.48 MAE / 85.3% coverage; global 49.64 / 55.5%; zero-fill 21.34 / 74.3%
- P(feature=1 | null) = 4.1%
- Cost: $0.20 for 240 emails
- 242 offline tests
- 31 decision entries (D1–D31, D19 reserved)
- Codebase: 29,059 real commits; PR lead time rejected (beta = -0.892)
- 15 features, 5 groups, 2^15 = 32,768 combinations
- Ridge alpha 0.3; 2,000 Monte Carlo draws; 3-day floor

## Tone
Confident, calm, evidence-first. No hype. No apology for not using MCP/markdown ceremony.
The deck should feel like a product review at a fintech, not a Twitter demo.
