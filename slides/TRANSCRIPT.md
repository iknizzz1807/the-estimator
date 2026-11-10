# Presentation transcript — how I built The Estimator

Deck: submitted `the-estimator-bizops.pdf` / `main-bizops.tex`, **unchanged**.
Audience brief: walk through how the project was built, how AI was used, and challenges encountered.
Language: spoken English. Square-bracketed notes are NOT spoken.
Target: 12–13 minutes. Hard stop: 15 minutes. Times are rehearsal allocations, not measured delivery.

## Before you start

- The story is **contracts → bounded AI implementation → integration → failures → verified corrections**. It is not a product sales pitch or a statistical defense.
- Protect slides 8, 9, and 11. Move quickly through packages and the learning curve.
- Only read the quoted paragraphs. Do not read captions or preparation notes.
- The deck's kicker numbers differ from its actual page numbers. Use actual page numbers below.
- Open the app, Git history, `docs/API.md`, and the D28/D31 evidence for questions.
- Verify personal details: actual coding models, one real prompt/task, and your own actions. Commits establish code changes, not every interaction or who suggested each idea.
- Important chronology: contracts and hybrid design existed at the start on October 16. The missing-data experiments and correction were committed October 23–24, **after Fest Night**. Do not present them as pre-submission work.
- Important labels: slide 3 numbers are MAE; slide 6 percentages are probability of exceeding an effort budget; slide 11's 4.1% means positive among null fields, not the unknown rate.

## Slide 1. Cover — the purpose of this walkthrough (0:00–0:35)

> Thanks for having me. I'm Thong. Today I'll walk through how I built The Estimator: how I broke down the challenge, used AI coding agents, and worked through implementation and design mistakes.
>
> The app turns a client request into an effort range and follow-up questions. I'll keep the product overview brief and focus on the build, including what I improved after Fest Night.
>
> The thread is simple: AI helped me produce code; I remained responsible for what that code meant and whether it worked.

[Point briefly at the range and the question mark. Move on.]

## Slide 2. The problem — make the task concrete (0:35–1:15)

> I started with a workflow, not a chatbot: receive a request, identify scope, surface missing details, and prepare an estimate someone can review.
>
> This payments email illustrates the problem. It mentions mobile and compliance, but doesn't answer every scope question. The time and questions shown here are illustrative.
>
> I defined three states for each feature: present, explicitly absent, and unknown. That turned an open-ended problem into something I could specify, delegate to coding agents, and test.

[The Digitization Service tag is a later connection, not a claim that you had observed Anduin's internal process.]

## Slide 3. Why LLM-only fails — test, don't assume (1:15–1:55)

> I also benchmarked direct LLM estimates. Without company effort history, I used synthetic projects for controlled testing—not evidence of real-world accuracy.
>
> These numbers are mean absolute errors on the final 42 projects: 258 person-days for LLM-only and 19 for the recorded-feature estimator. The inputs differ: one reads incomplete emails, the other uses recorded features.
>
> Five repeats on one email gave the same answer. Stability alone wasn't enough. These tests helped me examine the design; they weren't the origin of every architectural decision.

[Don't narrate “first prompt failed by 258, then I invented the split.” The earliest committed specification already contains the split.]

## Slide 4. The trade-off — decide the boundary before delegating (1:55–2:35)

> The hybrid design was already in my initial specification. I wanted a clear boundary between interpreting text and calculating effort.
>
> Direct LLM estimates were fast to implement. Fixed rules were inspectable but manually maintained. I chose extraction followed by a statistical estimator that could update from history.
>
> That meant more integration work, but gave the coding agents separate responsibilities and gave me clearer places to investigate when something failed.

[Point across the three options. Describe the trade-off, not a sequence of three fully built products.]

## Slide 5. The split — turn design into an implementation contract (2:35–3:20)

> I translated that boundary into contracts before the core implementation. Extraction returns fifteen named features with true, false, or null values, plus supporting quotes. Explicit negation and an unmentioned requirement must behave differently.
>
> The calculator returns effort quantiles. Ridge estimates effort, residual-based intervals represent prediction error, and Monte Carlo handles unresolved inputs.
>
> Those interfaces let me test calculation without a live LLM, and extraction without the frontend. The important development choice was making the boundaries explicit rather than asking an agent to generate one large, loosely defined application.

[Quote verification flags mismatches; it is not a hard gate that blocks every unsupported feature. Explain that if asked.]

## Slide 6. The quote — show the output, briefly (3:20–3:40)

> This is the user-facing result: scope scenarios against a 100-person-day budget. The percentages mean estimated probability of exceeding that effort budget, not percentage extra effort or calendar delay.
>
> Any scope reduction still needs client agreement. Now, how did I verify the system behind this screen?

[Point at Essential and 46%. Don't read all three cards.]

## Slide 7. Proof — checks that guide the build (3:40–4:25)

> I used offline tests for behavior, real provider calls for extraction, and chronological replay for estimation. Each of the 218 replay predictions trained on earlier rows.
>
> Testing the extraction path mattered: its error is 20.48, compared with 17.36 using recorded features. Also, the raw synthetic team baseline is deliberately biased. Corrected, it's 18.26, so the headline doesn't establish superiority over human estimators.
>
> What mattered for development was that these comparisons exposed weaknesses. The app could run and still contain a wrong assumption. Here's how I managed the build and responded to that evidence.

[Point at 20.48. Leave F1, coverage formulas, and cost methodology for questions.]

## Slide 8. The vibe-coding loop — how I used agents (4:25–6:15)

> I used AI in two roles. DeepSeek performs extraction inside the app. OpenCode was the environment for coding agents that helped draft implementations, tests, and revisions. I defined the scope and acceptance boundaries.
>
> The first commit already contains the specification and API contract. The data generator, database layer, and core services follow. The decision log records parallel implementation with separate file ownership, then API wiring and frontend integration.
>
> That structure mattered. An extraction task had a schema and null rules. An API task had a response shape. Agents could work on bounded pieces without independently inventing incompatible interfaces.
>
> I used QA agents for different review areas: backend edge cases, frontend integration, and repository hygiene. The resulting fixes included concurrent estimates colliding on IDs, non-finite effort values, and missing deployment dependencies. Generated code needed integration review, not just more generation.
>
> Deployment also changed the design. I consolidated the frontend and API into one service. Then a cloud build failed because it lacked the Git metadata available locally. The fix made that dependency conditional; later a fallback clone restored the optional self-analysis feature.
>
> Most of this was built on a phone. A frontend build failed on Android's shared filesystem, so the documented workaround was to build inside the Linux root filesystem and copy the artifacts back. The lesson was to adapt the environment while keeping the checks, not skip verification because the setup was difficult.

[Don't read the bottom build log as a literal first-prompt timeline. Sources: c0f5cef, D5, D7, D16, e0a83d3, ab6519c, 8f1cd42.]

## Slide 9. Six checks — a concrete review failure (6:15–7:40)

> These six checks are easier to explain through a bug than a checklist.
>
> The optional repository analyzer used code coverage as one risk signal. Local and cloud verification produced different scores for the same project. I needed to understand the mismatch rather than accept whichever number looked better.
>
> The search had found a coverage report from a generated demo repository nested inside the checkout. It was valid XML, but evidence about the wrong repository. That fixture wasn't present in the cloud.
>
> The correction checked whether the report referenced files in the analyzed checkout. Otherwise coverage became unknown. The commit includes a regression test recreating the unrelated-report case, and records matching local and cloud scores after the fix.
>
> That's what the evidence check meant in practice: trace the output to its source, fix the boundary, and preserve a test. A valid file and a successful parse weren't enough to make the result trustworthy.

[Evidence: d72eec7; `test_coverage_from_another_repo_is_ignored`. Don't claim the implemented file-existence check is a complete provenance guarantee.]

## Slide 10. The bottleneck — what AI didn't remove (7:40–8:10)

> These bars are illustrative, not a measured ten-times speedup. The practical lesson was that drafting accelerated faster than I could review and integrate.
>
> So I needed bounded changes, shared contracts, and repeatable checks. More agents weren't automatically better if I couldn't inspect their combined output.
>
> But the next challenge wasn't just an implementation bug. The specification itself needed to change.

## Slide 11. The mistake — revise the assumption (8:10–9:55)

> After Fest Night, I investigated the handling of unknown features more deeply. The October 23 experiment randomly hid features; that made the original Monte Carlo approach look encouraging.
>
> The next day's replay used actual LLM-extracted features. Error was 49.64 days, compared with 21.34 for simply filling unknowns with zero. The more elaborate approach was making things worse.
>
> External review challenged the assumption. The question became: why was a field unknown? Randomly hidden features and requirements the email didn't mention weren't the same population.
>
> Overall, about 25% of feature cells were positive. But among extraction-null cells, only 4.1% were positive. That's what 4.1% means here. The old sampler was inventing too much scope.
>
> The fix used feature-specific probabilities conditioned on extraction leaving a field null. I compared the old sampler, zero-fill, and the conditional sampler on the same chronological replay, estimating the new prior from earlier rows. Error fell to 20.48, and coverage improved to 85.3%.
>
> I recorded the failed approach and the correction. This is the most important lesson from the build: an agent can implement the requested behavior while the assumption behind it is wrong. Ownership includes accepting review, changing the assumption, and verifying the correction—not just asking AI for another patch.

[Evidence: 3d89142 → 531d8de → f94f78d; D31 explicitly credits external review. These are later improvements, not claimed pre-Fest results.]

## Slide 12. Company data — preserve the next debugging opportunity (9:55–10:20)

> This also reinforced the value of preserving useful history: the request, reviewed features, estimate, and actual effort.
>
> The slide compares separate synthetic corpus evaluations, not a guaranteed learning curve. The build lesson is to keep the inputs and outcomes needed to evaluate the next iteration rather than rely on memory.

[Move on.]

## Slide 13. The transfer — reuse the method (10:20–11:00)

> What I'd bring to Digitization Service is this way of working: understand the document workflow, define the output and review boundary, and give AI bounded implementation tasks.
>
> Your fields, business rules, data policies, and integrations would need to be learned with the team. I'd reuse the evidence and review pattern, not assume this estimator fits fund documents unchanged.
>
> The transferable experience is turning messy input into a reviewable first pass, then investigating where it breaks.

[Point across the two rows. Do not claim you know their volume, current tools, or ROI.]

## Slide 14. First 90 days — start with the people doing the work (11:00–11:50)

> I'd agree priorities with the team and start by following one real workflow: existing tools, normal cases, exceptions, and where people spend time correcting things.
>
> Then I'd build one small slice with those users and pilot it with approval still in place. It might need AI, a script, or just better validation rules.
>
> We'd compare total handling time and quality, including review and rework. Keep what helps, document how to operate it, and change direction if the benefit isn't there.
>
> The deliverable is something the team can use and maintain, not just something I can demonstrate.

## Slide 15. Close — what I want you to remember (11:50–12:30)

> The result is a shipped app, a recorded suite of 242 offline tests, and a decision log that includes failures as well as improvements.
>
> More importantly, you've seen how I build: define the task, use AI to accelerate implementation, inspect the integration, and change direction when evidence contradicts an assumption.
>
> That's the ownership I'd bring to your team. Thank you. I'm happy to open the code or go deeper on any build challenge.

[Stop. Don't fill the silence with additional caveats.]

---

## Cue card

| Slide | End time | One line |
|---|---|---|
| 1 | 0:35 | Build walkthrough, including later improvements. |
| 2 | 1:15 | Workflow → three states → a bounded task. |
| 3 | 1:55 | Benchmark tested the design; it didn't invent the timeline. |
| 4 | 2:35 | Define the LLM boundary before delegating. |
| 5 | 3:20 | Contracts make modules testable and integration inspectable. |
| 6 | 3:40 | Output briefly; risk probability, not extra days. |
| 7 | 4:25 | Evaluation locates weaknesses; qualify synthetic comparison. |
| 8 | 6:15 | Parallel agents, QA, deployment, environment constraints. |
| 9 | 7:40 | Wrong repository's report → boundary fix → regression. |
| 10 | 8:10 | Review and integration remain the bottleneck. |
| 11 | 9:55 | Post-Fest experiment → review → wrong prior → verified fix. |
| 12 | 10:20 | Preserve evidence for the next iteration. |
| 13 | 11:00 | Transfer the building method, not the app unchanged. |
| 14 | 11:50 | Learn with users, pilot one slice, measure and document. |
| 15 | 12:30 | Clear tasks, verified integration, ownership. |

## If you need a 10-minute cut

- Pass over slides 6 and 12 with one short sentence each.
- Shorten slides 3–5 by explaining the architecture once rather than repeating it.
- On slide 8, omit the phone-build detail and keep the contracts, agent coordination, and deployment example.
- Shorten slides 13–14; don't cut the concrete stories on slides 9 and 11.
- Keep synthetic disclosure, correct metric meanings, and post-Fest chronology.
- Rehearse aloud. Word counts and allocations do not measure your actual delivery.

## Preparation, not spoken

- Read `slides/VIBE_CODING_STORY.md` for the fuller Git-grounded narrative.
- Practice `slides/QA.md` first; use `slides/QA_EVIDENCE.md` only for deeper technical follow-ups.
- Fill one real coding-agent task example: instruction → context → constraints → generated output → your inspection → verification.
- Confirm actual coding models and personal actions from memory or saved sessions. Do not infer them from commit authorship.
- Keep two stories ready: D28 for an implementation/integration mistake; D31 for a wrong specification assumption.
- Do not imply the reviewer contribution diminishes yours. Acting on valid feedback and verifying the correction is part of ownership.
