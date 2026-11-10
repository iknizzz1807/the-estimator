# Presentation transcript

Deck: `main-bizops.tex` (15 slides, no headlines).
Language: spoken English. Vietnamese notes are in square brackets.
Target: 12 to 13 minutes. Hard stop: 15:00.

## Before you start

- Set a timer for 12:30. Hard stop at 15:00.
- Do not read the kicker numbers. They do not match the footer page numbers.
- Do not read the captions. They are for the panel to read.
- Keep the app and repo tabs open. The QR code is on the last slide.
- This script accompanies the submitted deck; no slide changes are required.
- Timing below is a rehearsal budget, not a measured speaking duration. Rehearse aloud.
- Important slide clarifications: slide 3 = MAE, not accumulated error; slide 6 = probability of overrun; slide 11 = 4.1% positive among null fields, not 4.1% unknown.
- Delivery: explain the decision, then the result. Do not read the preparation notes or turn each slide into a disclaimer. Keep the evaluation limits on slides 3 and 7 explicit.

## Slide 1. Cover (0:00 to 0:40)

> Thanks for having me. I'm Thong. When a client sends a request, someone has to turn it into a commitment: scope, effort, and unanswered questions.
>
> I built The Estimator to make that conversation more structured. It turns the request into an effort range, with extracted fields and source quotes to review.
>
> Today I'll focus on the decisions behind it, how I used AI to build it, and one mistake that changed my approach.

[Point at 79 / 111 / 191, then at the ? on data_migration.]

> The key is that question mark. Missing information should become a useful question—not disappear inside a confident number.

## Slide 2. The problem (0:40 to 1:30)

> Imagine handling this payments request: mobile apps, PCI compliance, live updates. Specific, but still incomplete.
>
> Even after hours of reading and questions, you might struggle to explain the estimate. That's the scenario here.

[Point at the sticky note "How many days?" and the chip "still a guess".]

> So I focused on the first pass: separate what's requested, what's explicitly ruled out, and what's unknown. Then show which missing answers could change the estimate most.
>
> The user gets a structured conversation, rather than an unexplained number.

[Point at the tag in the top right.]

> That document-to-structured-data problem is also the connection I see to Digitization Service. I'll come back to it at the end.

## Slide 3. Why LLM-only fails (1:30 to 2:35)

> Could I just ask an LLM for the number? I tested that. Since I didn't have company effort history, I generated 240 synthetic projects. This is a controlled simulation, not evidence of real-world estimation accuracy.
>
> On the same 42 recent projects, the LLM-only baseline had a mean absolute error of 258 person-days. The estimator had 19.

[Point at 258 and 19.]

> The estimator used recorded features; the LLM read emails. It's not an equal-input comparison. I'll show the extraction-path result shortly.
>
> Five repeats on one email also gave the same answer. It was stable on that sample, but stability wasn't enough. I wanted a calculation anchored to project history, with assumptions I could inspect.

## Slide 4. The trade-off (2:35 to 3:15)

> That led to the central design decision: what should the LLM be responsible for?
>
> Three options: A, let the LLM estimate directly—fast, but hard to justify. B, extract into fixed rules—inspectable, but manually maintained. C, extract into a statistical estimator that learns from completed work.
>
> I chose C: more implementation work for a traceable calculation and a feedback loop.

[Point at rejected, trade-off, chosen in that order.]

## Slide 5. The split (3:15 to 4:05)

> The LLM's authority stops at this line.

[Point at "LLM stops here".]

> On the left, the LLM handles language. It extracts 15 features and is asked to quote the supporting text. The service checks those quotes against the email and flags mismatches for review.
>
> On the right, the calculation handles effort. Ridge learns relationships from history. Residual-based intervals represent prediction error. Monte Carlo carries unresolved features into the range.
>
> If the email doesn't mention a feature, it stays unknown rather than automatically becoming absent. The system models that uncertainty and ranks follow-up questions.
>
> When something goes wrong, I can investigate separately: misunderstood request, missing information, or estimation error?

## Slide 6. The quote (4:05 to 4:55)

> Now the salesperson has a budget of 100 person-days—engineering effort, not a delivery date. The three scope options have median estimates of 95, 119, and 207.
>
> Essential looks affordable at the median. But 46% means estimated probability of exceeding budget, not extra effort. The other risks are 63% and 91%. All exceed the configured 25% threshold.

[Point at the 100-day budget line and at 46 / 63 / 91 percent.]

> Could mobile be phased later? Is there contingency? The client must agree to scope changes. The tool exposes the trade-off; the user owns the commitment.

## Slide 7. Proof (4:55 to 6:10)

> Of the 240 synthetic projects, 228 were completed. Starting with ten for training gave 218 walk-forward predictions, each using only earlier rows.
>
> With recorded features, mean absolute error was 17.36 person-days. The interval contained 86.7% of outcomes. That's measured coverage on this simulation.
>
> The “half the error” comparison uses a synthetic team baseline deliberately biased low. After correcting that bias, its error is 18.26 rather than 32.93.

[Point at 20.48 in the lower band. Keep recorded-feature and extracted-feature results separate.]

> And with extracted features, the system's error is 20.48, with 85.3% coverage. So I don't claim it beats human estimators: it doesn't beat even the corrected synthetic baseline here.
>
> Extraction micro-F1 was 0.933 on 236 evaluated emails; four failed. Estimated batch cost was about twenty cents. These measurements let me locate weaknesses. To establish business value, the next test is a real workflow pilot measuring time, review effort, and quality.

## Slide 8. The vibe-coding loop (6:10 to 7:15)

> How did I build with AI? OpenCode helped write most of the code; DeepSeek runs inside the product. I defined the tasks, constraints, and acceptance criteria.

[Point at the AI and Human panels, then follow the loop. Do not narrate the build log as a literal first-prompt chronology.]

> I split the work around documented contracts: extraction returns fields, estimation returns ranges, and the API connects them to the UI. Coding agents got bounded tasks, not one instruction to build everything.
>
> Then I checked the joins: did the API return what the UI expected? Did a failed repository analysis preserve the estimate? Did the deployed container include what worked locally? The decision log records those integration fixes, not just successful outputs.
>
> Most was built on a phone, so small steps mattered: define, generate, inspect, test, measure, document. AI accelerated implementation; I kept responsibility.

## Slide 9. Six checks (7:15 to 7:50)

> These six checks made review concrete.
>
> Contract, failure modes, reproducibility, evidence, tests, rollback. Does it match the interface? Handle missing inputs? Catch broken behavior? Leave a traceable result and a clean way back?

[Point at Evidence and Determinism.]

> For reproducibility, I fix the calculation's inputs and random seeds. For external model behavior, I use evaluation. That distinction helps me know what a passing test actually tells me.

## Slide 10. The bottleneck (7:50 to 8:20)

> These bars illustrate the bottleneck: drafting accelerates faster than review. Faster generation helps only if I can check what I'm shipping.
>
> That's why I invest in shared evaluation sets, repeatable checks, and small diffs—not just better prompts.

[Point at throughput cap and the equation shipped = min(generation, review).]

> Optimize the whole workflow, including review and rework. Here's where evaluation changed an implementation I thought was reasonable.

## Slide 11. The mistake (8:20 to 9:35)

> My first Monte Carlo version used a simple assumption: if a feature is unknown, sample it using how often it appears in history—about 25% overall.
>
> A random-masking experiment looked encouraging. But when I evaluated actual extracted features, error was 49.64 days. Simply filling unknowns with zero gave 21.34. My more elaborate approach was making things worse.

[Point at 25%, then 49.64 versus 21.34. The failed version was marginal sampling, NOT zero-fill.]

> So I stopped tuning and checked what “unknown” meant. The extractor left a field null when the email didn't mention it. Among those null fields, only 4.1% were actually positive. That's the meaning of 4.1% here: present despite being unmentioned.
>
> Sampling at 25% was inventing too much scope. I changed the sampler to use the rate among null fields, estimated from earlier rows in the replay. Error fell to 20.48, and coverage rose from 55.5% to 85.3%.
>
> That's the most useful lesson from the build: before asking AI to improve the code, check whether you've given it the right problem. The fix was a better assumption about the data, not a more powerful model.

## Slide 12. Company data (9:35 to 10:15)

> That brings me to the data loop. In the simulation, expanding from 60 to 240 total projects reduced aggregate replay error from 23.50 to 17.36. These are separate corpus evaluations, so I treat this as an illustration of the feedback loop, rather than a guaranteed learning curve.
>
> Record the request, reviewed features, estimate, and actual effort when work finishes.

[Point at "same model, more history" and at 60 to 240.]

> The company-specific asset is reliable history. Consistent effort definitions and reviewed outcomes give the next estimate something better to learn from.

## Slide 13. The transfer (10:15 to 11:00)

> What transfers to Digitization Service? The pattern: extract structured fields, retain source references, validate, and route exceptions to a reviewer.
>
> For a fund document, the fields and business rules would be different. I'd define those with the team, along with the risk thresholds, approved data handling, and integrations.
>
> I'd reuse the separation of responsibilities, not deploy this estimator unchanged.

[Point at the vertical dashed guides between the two rows.]

> The goal is a tool that helps people finish the work with less manual effort and rework, while keeping quality under control. Here's how I'd start finding that opportunity.

## Slide 14. First 90 days (11:00 to 12:00)

> I'd agree the priorities with the team, then work in three stages.
>
> First two weeks: sit with the people doing the work. Follow one workflow, understand existing tools, and measure total handling time, rework, and critical errors. Choose one recurring problem with a clear owner.
>
> Days 15 to 45: build one small slice with those users and pilot it alongside the current process. Keep source evidence and human approval in place. Use AI where it helps; use rules or a simpler tool where that's enough.
>
> Days 46 to 90: compare the whole workflow against the baseline, including review and maintenance. If it helps without compromising quality, document it and expand carefully. If it doesn't, change direction or stop.
>
> The deliverable isn't just an app. It's a useful workflow the team can operate and maintain.

[Point at the three GATE bands.]

## Slide 15. Close (12:00 to 12:30)

> The Estimator is shipped, with 242 offline tests and a documented record of what worked and what didn't—including five negative results.
>
> What I'd bring to Anduin is that ownership: understand the business problem, use AI to build quickly, and stay responsible for whether the result actually helps the team.
>
> The repo is behind the QR code. Thank you. I'm happy to walk through a build decision, a failed experiment, or how I'd apply this approach with your team.

[Stop. Invite questions.]

---

# Cue card

| Slide | Time | One line to remember |
|---|---|---|
| 1 | 0:40 | Turn a request into a commitment; unknowns become questions. |
| 2 | 1:30 | Illustrative scenario; structured first pass. |
| 3 | 2:35 | Synthetic; 258 vs 19 MAE; unequal inputs. |
| 4 | 3:15 | Separate interpretation from calculation. |
| 5 | 4:05 | Separate language from calculation so failures are traceable. |
| 6 | 4:55 | Person-days; probability of overrun; discuss scope. |
| 7 | 6:10 | Recorded 17.36; extracted 20.48; no human-superiority claim. |
| 8 | 7:15 | Bounded AI tasks; contracts first; verify integration. |
| 9 | 7:50 | Six concrete checks; reproducible calculation, evaluated LLM. |
| 10 | 8:20 | Faster drafts need review capacity; optimize the whole workflow. |
| 11 | 9:35 | Wrong 25% prior; 4.1% positive among nulls; fix and remeasure. |
| 12 | 10:15 | Capture reviewed actuals; reliable history is the asset. |
| 13 | 11:00 | Transfer the pattern; discover rules and data constraints. |
| 14 | 12:00 | Shadow, pilot, measure total workflow value. |
| 15 | 12:30 | Build quickly; stay responsible for business usefulness. |

## 10-minute cut

Skip slides 6 and 12 (saves about 90 seconds). Summarize slide 9 in one sentence and slide 10 in one sentence (saves about 40 seconds). Keep the synthetic-data disclosure, the slide 7 comparison limits, and the slide 11 failure story. Rehearse the cut aloud rather than relying on these estimated savings.

## Q&A preparation — not part of the spoken script

Keep these details available; do not add every caveat to the presentation.

- **What does the synthetic evaluation establish?** Pipeline behavior under a controlled data-generating process, not real-world accuracy. Actual effort was generated from multiplicative feature effects, interactions, drift, and noise; log-Ridge is well matched to the main-effects structure. The synthetic team baseline was deliberately biased low.
- **Does it outperform humans?** Not established. Recorded-feature MAE is 17.36; extracted-feature MAE is 20.48; the corrected synthetic-team baseline is 18.26. Workflow benefits such as time savings and consistency need a real pilot.
- **Why 19 on slide 3 but 17.36 on slide 7?** 19.25 is the recorded-feature MAE on the final 42 replay steps; 17.36 is on all 218. The 258.12 LLM-only number is also MAE on those same 42, not a sum or a single failed prompt.
- **Are the quotes a hard evidence gate?** No. The service uses fuzzy quote matching (threshold 85%). A mismatch removes the quote and reduces confidence, but retains the feature value. A stricter production gate would require support or review before using an unsupported value. A matching quote also needs semantic validation.
- **Is this true split conformal with a formal coverage guarantee?** The deployed method uses out-of-fold residual quantiles and a tuned 1.10 tail widening. Describe it as residual-based or conformal-style. The reported coverage is empirical; do not claim a formal guarantee under drift. See `docs/BASELINE_COMPARISON.md`.
- **Where does overrun probability come from?** A lognormal approximation fitted from the estimated interval. It is a model-based risk estimate, not an independently validated real-world probability. The 25% recommendation threshold is a configured policy, not a discovered business requirement.
- **What exactly is 4.1%?** In the extraction cache, 100 of 2,436 null cells were actually positive. About 71.2% of feature cells were unresolved; 4.1% is not the unknown rate. The evaluation estimates feature-specific null priors from earlier rows. The deployed demo loads a prior file built from completed history, so distinguish deployment from historical replay.
- **What does extraction F1 measure?** Micro-F1 for positive-feature detection against recorded labels on 236 evaluated synthetic emails. Four failed after retry. It is not overall field accuracy, quote accuracy, or validation on fund documents. Cost is a rough token-based estimate, not an invoice.
- **What changed in the learning curve?** The corpus expanded from 60 to 240 total projects; 240 does not mean 240 completed training examples. Aggregate replay scores on different corpora do not isolate a fixed-test-set data-size effect.
- **Which code was AI-generated, and what did you personally decide?** Explain only steps you remember or can substantiate. Use the documented contracts, integration fixes, and missing-prior evaluation as evidence. Do not invent a literal prompt, chat exchange, commit, or development chronology.
- **Where can the panel inspect evidence?** `docs/AB_MEASUREMENT.md`, `docs/ENDTOEND_REPLAY.md`, `docs/BASELINE_COMPARISON.md`, `docs/EXTRACTION_EVAL.md`, and `docs/DECISIONS.md` (especially D16–D17, D21, D28, and D31). The 242 figure refers to the recorded offline suite, not a new verification run during script editing.
