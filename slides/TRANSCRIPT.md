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

## Slide 1. Cover (0:00 to 0:40)

> Thanks for having me. I'm Thong. I'll keep the product overview brief and focus on how I built it: the decisions, the AI-assisted process, and what testing changed.
>
> The product is The Estimator. It turns a client's request into an effort range and highlights the questions still worth asking.
>
> What I want to show is the way I work: use AI to draft, make assumptions explicit, and check the result before trusting it.

[Point at 79 / 111 / 191, then at the ? on data_migration.]

> Here's the idea: a range, the extracted fields behind it, and source quotes for review—not just a confident number.

## Slide 2. The problem (0:40 to 1:30)

> Here's an illustrative payments request. It tells you what the client wants, but not the engineering effort involved.
>
> The two hours and three questions on the slide illustrate the problem; they're not measured time savings. Someone still has to interpret the request, identify missing details, and make an estimate.

[Point at the sticky note "How many days?" and the chip "still a guess".]

> I focused on making that first pass structured: what is explicitly requested, what is ruled out, and what is still unknown?
>
> That gives the salesperson something to review and discuss with the client, instead of one unexplained number.

[Point at the tag in the top right.]

> The connection to Digitization Service is the document-to-structured-data pattern. I'll return to what transfers—and what still needs discovery—at the end.

## Slide 3. Why LLM-only fails (1:30 to 2:35)

> One important assumption before the results: I didn't have real company effort history. I generated 240 synthetic projects to test the pipeline under controlled conditions. These are not real-world accuracy claims.
>
> On the same 42 recent projects, the LLM-only baseline had a mean absolute error of 258 person-days. The estimator had 19.

[Point at 258 and 19.]

> This comparison isolates part of the problem: the estimator used recorded features, while the LLM read the emails. It's not an equal-input, end-to-end comparison. I'll show the extraction-path result shortly.
>
> Five repeats on one email gave the same answer. That only demonstrates stability on that sample, not accuracy or the cause of error. The practical lesson was to anchor effort estimates to history, rather than trust a direct language-model answer.

## Slide 4. The trade-off (2:35 to 3:15)

> My main decision was architectural, not just about prompting.
>
> These are three designs I considered. A: let the LLM read and estimate directly. Fast to build, but the number is difficult to justify. B: extract into fixed rules. Easy to inspect, but the rules need maintenance. C: extract into a statistical estimator that can update from completed work.
>
> I chose C. More moving parts, but a clearer boundary between interpreting a request and calculating effort.

[Point at rejected, trade-off, chosen in that order.]

## Slide 5. The split (3:15 to 4:05)

> The LLM's authority stops at this line.

[Point at "LLM stops here".]

> Left side: language to structure. The LLM extracts 15 features and is instructed to quote the supporting text. The service checks quote matches and flags problems. That's a review aid, not a guarantee that every field is correct.
>
> Right side: structure to range. Ridge learns effort relationships from history. Residual-based intervals represent prediction error. Monte Carlo handles unresolved features.
>
> If the email doesn't mention a feature, it stays unknown rather than automatically becoming absent. The system models that uncertainty and ranks follow-up questions.
>
> The calculation is reproducible, but its usefulness still depends on the features, the history, and the assumptions. Separating the parts makes those assumptions easier to test.

## Slide 6. The quote (4:05 to 4:55)

> Here's an example against a budget of 100 person-days. The median effort estimates are 95 for Essential, 119 for Standard, and 207 for Full. These are effort units, not calendar delivery dates.
>
> The percentages mean estimated probability of exceeding the budget—not percentage over budget. Essential is below budget at the median, but still carries a model-estimated 46% overrun risk. None meets the tool's 25% risk threshold.

[Point at the 100-day budget line and at 46 / 63 / 91 percent.]

> These are scope scenarios to discuss, not permission to remove requirements. For example, dropping mobile only makes sense if the client agrees. The value is making the scope-and-risk conversation explicit.

## Slide 7. Proof (4:55 to 6:10)

> There were 228 completed synthetic projects. Starting with ten for training left 218 walk-forward predictions, each trained only on earlier rows.
>
> With recorded features, MAE was 17.36 person-days, and 86.7% of outcomes fell inside the interval. That's observed coverage on this simulation, not a guarantee for future projects.
>
> The headline's comparison with 32.93 uses a deliberately low-biased synthetic team estimate. Correcting that baseline gives 18.26, so “half the error” should not be read as beating real human estimators by half.

[Point at 20.48 in the lower band. Keep recorded-feature and extracted-feature results separate.]

> Using extracted features, MAE was 20.48 and coverage was 85.3%. That does not beat the corrected baseline here.
>
> Extraction micro-F1 was 0.933 across 236 successfully evaluated emails; four failed. The batch cost estimate was about twenty cents. What this establishes is a working, measured prototype—not proven business impact. That needs a real pilot.

## Slide 8. The vibe-coding loop (6:10 to 7:15)

> Most of the code was written with OpenCode. DeepSeek does the extraction. The AI did the drafting; I owned the loop: decide, constrain, generate, review, test, measure, document.

[Point at the AI and Human panels, then down at the build log.]

> Read the build log as a summary of the design, not a single prompt's history: 258 is the benchmark's average error, not one first attempt. The boundary I chose was extraction-only for the LLM, with the calculation outside it.
>
> I broke the build into modules around documented interfaces: extraction, estimation, API, and UI. AI could draft implementations and tests against those contracts. My job was to check integration, challenge assumptions, and compare the results with baselines.
>
> Most of this was built on a phone, which encouraged small steps. But the useful part isn't the device: it's keeping changes small enough to inspect. The missing-data failure in a moment is a concrete example of why that matters.

## Slide 9. Six checks (7:15 to 7:50)

> Review is six specific checks, not a vibe.
>
> Contract: does it match the interface? Failure modes: empty, None, huge input? Determinism: same input, same output? Evidence: can I trace the number? Tests: does it fail when I break it? Rollback: can I revert in one commit?

[Point at Evidence and Determinism.]

> Determinism here means the calculation with fixed inputs and seeds, not a promise that an external LLM never changes. And passing tests doesn't prove the design assumptions are right—that needs evaluation too.

## Slide 10. The bottleneck (7:50 to 8:20)

> The ten-times and one-times bars are illustrative, not a measured productivity result. The point is that faster drafting doesn't automatically mean faster delivery.
>
> Review can become the bottleneck. So I invest in shared evaluation sets, repeatable checks, and small diffs—not just better prompts.

[Point at throughput cap and the equation shipped = min(generation, review).]

> In an operations workflow, I'd measure the whole process, including review and rework, rather than celebrate how fast AI produces a first draft.

## Slide 11. The mistake (8:20 to 9:35)

> Here's a real implementation mistake. The first Monte Carlo version sampled unknown features using their overall historical prevalence—about 25%.
>
> It sounded reasonable, and a random-masking experiment looked encouraging. But actual extraction nulls were not random missing values. On the extraction path, that prior produced 49.64 days MAE—worse than the simple zero-fill baseline at 21.34.

[Point at 25%, then 49.64 versus 21.34. The failed version was marginal sampling, NOT zero-fill.]

> I checked what “unknown” actually meant. Only 4.1% of fields left null were truly positive. That's what the 4.1% on the slide refers to—not the percentage of fields that were unknown.
>
> I changed the sampler to use the probability of a feature being present given that extraction left it null. In the evaluation, that prior was estimated from earlier rows only. MAE fell to 20.48, and coverage rose from 55.5% to 85.3%.
>
> The lesson for AI-assisted building: passing a test under the wrong assumptions isn't enough. I had to change the assumption and the evaluation, not just ask AI to tune the model.

## Slide 12. Company data (9:35 to 10:15)

> The same model family can improve when the history improves. In this simulation, expanding the corpus from 60 to 240 total projects reduced aggregate replay MAE from 23.50 to 17.36.
>
> Those are two corpus-level evaluations, not a fixed-test-set learning curve, so I wouldn't promise the same improvement in production.

[Point at "same model, more history" and at 60 to 240.]

> The practical takeaway is to capture the original request, reviewed features, the estimate, and actual effort when work finishes.
>
> Reliable company history is the asset. More rows alone aren't enough; the definitions and review quality have to stay consistent.

## Slide 13. The transfer (10:15 to 11:00)

> This is a proposed transfer of the pattern, not a claim that this app is ready for fund documents.
>
> A document comes in. Extract fields with source references. Validate against business rules. Route exceptions to a human reviewer.
>
> What's reusable is the separation of interpretation, validation, and human approval. The actual fields, risk thresholds, and integrations would need to be defined with the team.

[Point at the vertical dashed guides between the two rows.]

> I'd also need to understand approved data handling before using any AI provider. The business question is whether this pattern reduces total handling time without lowering quality—not whether I can reuse my stack.

## Slide 14. First 90 days (11:00 to 12:00)

> This is a starting proposal, subject to the team's priorities and access requirements.
>
> First two weeks: shadow one workflow, understand the users and existing automations, and agree on a baseline: total minutes per document, review and rework, and critical errors. Pick a narrow problem with a clear owner.
>
> Days 15 to 45: pilot one small slice alongside the existing process. Keep evidence attached and human approval in place. It could be AI, rules, or a simpler tool—whichever fits the problem.
>
> Days 46 to 90: compare against the agreed baseline, including the cost of review and maintenance. Keep it if it improves the workflow without compromising quality. Otherwise, change direction or stop, and document what we learned.

[Point at the three GATE bands.]

## Slide 15. Close (12:00 to 12:30)

> The result is a deployed prototype, 242 offline tests, and a record of experiments—including five negative results. It's not a production-readiness claim.
>
> What I'd bring to Anduin is the same ownership: understand the work, use AI to build, test the assumptions, and measure whether the tool actually helps the team.
>
> The repo is behind the QR code. I'm happy to go deeper on the build process, the evaluation, or any trade-off.

[Stop. Invite questions.]

---

# Cue card

| Slide | Time | One line to remember |
|---|---|---|
| 1 | 0:40 | Product briefly; focus on decisions and ownership. |
| 2 | 1:30 | Illustrative scenario; structured first pass. |
| 3 | 2:35 | Synthetic; 258 vs 19 MAE; unequal inputs. |
| 4 | 3:15 | Separate interpretation from calculation. |
| 5 | 4:05 | Quotes support review; assumptions still need testing. |
| 6 | 4:55 | Person-days; probability of overrun; discuss scope. |
| 7 | 6:10 | Recorded 17.36; extracted 20.48; no human-superiority claim. |
| 8 | 7:15 | AI drafts modules; I own contracts, integration, evaluation. |
| 9 | 7:50 | Six checks; tests don't establish valid assumptions. |
| 10 | 8:20 | Bars illustrative; measure review and rework too. |
| 11 | 9:35 | Wrong 25% prior; 4.1% positive among nulls; fix and remeasure. |
| 12 | 10:15 | Better history is an asset, not a guaranteed learning curve. |
| 13 | 11:00 | Transfer the pattern; discover rules and data constraints. |
| 14 | 12:00 | Shadow, pilot, measure total workflow value. |
| 15 | 12:30 | Working prototype; responsible ownership. |

## 10-minute cut

Skip slides 6 and 12 (saves about 90 seconds). Summarize slide 9 in one sentence and slide 10 in one sentence (saves about 40 seconds). Keep the synthetic-data disclosure, the slide 7 comparison limits, and the slide 11 failure story. Rehearse the cut aloud rather than relying on these estimated savings.
