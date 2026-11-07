# Presentation transcript

Deck: `main-bizops.tex` (15 slides, no headlines).
Language: spoken English. Vietnamese notes are in square brackets.
Target: 12 to 13 minutes. Hard stop: 15:00.

## Before you start

- Set a timer for 12:30. Hard stop at 15:00.
- Do not read the kicker numbers. They do not match the footer page numbers.
- Do not read the captions. They are for the panel to read.
- Keep the app and repo tabs open. The QR code is on the last slide.

## Slide 1. Cover (0:00 to 0:40)

> Thanks for having me. I'm Thong. You've already used the app in round one, so I won't spend time demoing it. I want to show you the decisions behind it.
>
> For the next twelve minutes I'll walk through one project end to end: how I framed the problem, the trade-off I made, how I used AI to build it, and how I checked that it works.
>
> The product is an estimator. What I'm really showing is the loop I'd bring to Digitization Service.

[Point at 79 / 111 / 191, then at the ? on data_migration.]

> The output is a range, not a single number. Every field behind it carries a quote from the client's email. That's the idea: an estimate that shows its work.

## Slide 2. The problem (0:40 to 1:40)

> Here's the input: a payments RFP. It tells you what they want. It doesn't tell you how long it takes.
>
> Two hours of reading and three clarifying questions later, the answer is still a guess.

[Point at the sticky note "How many days?" and the chip "still a guess".]

> In a digitization queue, this is the same shape: a document comes in, someone reads it, extracts fields, and the exception is where the cost is.
>
> So the problem I picked was: can I make that first pass explicit, auditable, and fast?

[Point at the tag in the top right.]

> That tag is the reason I picked this problem. Same pipeline as Digitization Service.

## Slide 3. Why LLM-only fails (1:40 to 2:50)

> The obvious move is to give the whole thing to an LLM. I measured it.
>
> On the same 42 projects, the LLM-only baseline accumulated 258 days of absolute error. The system: 19.

[Point at 258 and 19.]

> And the important part is why. At temperature zero, five runs on the same email gave the same answer. Standard deviation zero.
>
> It wasn't random. It was confidently wrong, because it confuses calendar time with engineering days and has no anchor to this team's velocity. Re-running it or averaging ten samples doesn't fix calibration.

## Slide 4. The trade-off (2:50 to 3:45)

> So the fix wasn't a better prompt. It was an architecture choice.
>
> I considered three designs. A: LLM end to end. Fast, but no audit trail and no calibration. B: LLM plus rules. Auditable, but brittle, and it doesn't learn. C: LLM extracts, math estimates. Slower to build, but auditable, calibrated, and it learns.
>
> I chose C. I gave up speed to get a trail I could defend.

[Point at rejected, trade-off, chosen in that order.]

## Slide 5. The split (3:45 to 4:40)

> The LLM's authority stops at this line.

[Point at "LLM stops here".]

> Left side: language to structure. It reads the email, extracts 15 features, and every field carries a verbatim quote.
>
> Right side: structure to range. Ridge regression, conformal prediction, Monte Carlo.
>
> If a field is missing, it stays unknown. I don't fill it with zero. I widen the range and ask about it.
>
> The number isn't the model's opinion. It's arithmetic on evidence.

## Slide 6. The quote (4:40 to 5:35)

> Here's the same project against a 100-day budget. Essential is 95 days, Standard 119, Full 207.
>
> All three are over budget: 46, 63, and 91 percent. So the recommendation is Essential, and the next step is to renegotiate the budget or the timeline.

[Point at the 100-day budget line and at 46 / 63 / 91 percent.]

> The value isn't the three packages. It's that the salesperson can see the trade-off instead of arguing from one number.

## Slide 7. Proof (5:35 to 6:50)

> Out of sample, on 218 walk-forward steps, error was 17.36 days against 32.93 for the team's hand estimates.
>
> 86.7% of actual outcomes fell inside the P10 to P90 range. That's coverage, not accuracy.
>
> Extraction quality was 0.933, and the cost was about twenty cents for 240 emails.

[Pause for one beat. This is the credibility section.]

> One caveat I want to say before you ask. That 32.93 baseline is optimistic by construction. De-biased, it's 18.26. And on the real extraction path, the system is 20.48.
>
> So I don't claim this beats the team by half. The claims I will defend are: the extractor is accurate, the interval covers, and the whole thing is auditable.

## Slide 8. The vibe-coding loop (6:50 to 8:20)

> Most of the code was written with OpenCode. DeepSeek does the extraction. The AI did the drafting; I owned the loop: decide, constrain, generate, review, test, measure, document.

[Point at the AI and Human panels, then down at the build log.]

> The build log at the bottom is the short version. The first prompt gave a number, and it was 258 days off. I changed the task to extract only, added a quote per field, moved the math outside, and put six gates around every change.
>
> The important part isn't that AI wrote code fast. It's that every AI change went through the same gates as mine. That's how you get speed without losing the trail.
>
> Most of this was built on a phone, which forced the loop to stay small.

## Slide 9. Six checks (8:20 to 9:10)

> Review is six specific checks, not a vibe.
>
> Contract: does it match the interface? Failure modes: empty, None, huge input? Determinism: same input, same output? Evidence: can I trace the number? Tests: does it fail when I break it? Rollback: can I revert in one commit?

[Point at Evidence and Determinism.]

> These are what make another person's change defensible. They're also why I trust the numbers on the previous slide.

## Slide 10. The bottleneck (9:10 to 10:00)

> AI generation is roughly ten times. Human review is one times.
>
> Shipped throughput is the minimum of the two, so the gate sets the speed.

[Point at throughput cap and the equation shipped = min(generation, review).]

> That's why I invest in shared eval sets, the same six checks, and small diffs, not better prompts.
>
> If you're adopting AI in an operations team, review capacity is the thing you design, not the model.

## Slide 11. The mistake (10:00 to 11:00)

> My first version treated a missing feature as absent and zero-filled it.
>
> That made the estimate worse than doing nothing: 49.64 days of error versus 21.34 with the right prior.

[Point at "a null is not a zero" and at 49.64 / 21.34.]

> The fix was to treat a null as a question. Only 4.1% of fields stayed unknown, and error fell to 20.48.
>
> The lesson wasn't "tune the model." It was that the representation of missing data was wrong.
>
> I kept the failure in the deck because it's why the later numbers are believable.

## Slide 12. Company data (11:00 to 11:45)

> The model didn't change. The history did.
>
> With 60 finished projects, error was 23.50 days. With 240, it was 17.36.

[Point at "same model, more history" and at 60 to 240.]

> Every finished project becomes a training row: input, extracted features, quoted range, actual days.
>
> That row is the asset. The model is public; the company's actuals are not. That's the part that compounds.

## Slide 13. The transfer (11:45 to 12:35)

> Here's the same architecture for fund documents.
>
> Input: document. Extract: fields with quotes. Validate: reviewed record. Review: exception queue.
>
> The object changes; the gates don't.

[Point at the vertical dashed guides between the two rows.]

> The estimator is the proof that the loop works. Digitization Service is where the same loop has much larger volume and a clearer ROI.

## Slide 14. First 90 days (12:35 to 13:30)

> Days 1 to 14: shadow one fund document workflow, count rework, inventory existing automations. Baseline minutes per document, rework rate, exception rate. The gate is a number, not an opinion.
>
> Days 15 to 45: ship one document type end to end. Every field keeps its evidence; every exception has an owner. The gate: no unreviewed record leaves the queue.
>
> Days 46 to 90: re-run the baseline, keep what beats it, write the playbook. The gate: beats baseline, or it stops.
>
> That's the plan I'd bring.

[Point at the three GATE bands.]

## Slide 15. Close (13:30 to 14:00)

> It's shipped, tested, and honest: one container, one URL, 242 offline tests, and five negative results published.
>
> The review is the part I refuse to skip. You've seen the app; the repo is behind the QR code.
>
> I'm happy to go deeper on any trade-off, especially where this lands in Digitization Service.

[Stop. Invite questions.]

---

# Cue card

| Slide | Time | One line to remember |
|---|---|---|
| 1 | 0:40 | Range, not a number; evidence attached. |
| 2 | 1:40 | Email in, guess out; same pipeline as digitization. |
| 3 | 2:50 | 258 vs 19; zero variance, wrong calibration. |
| 4 | 3:45 | Three designs; chose the auditable one. |
| 5 | 4:40 | LLM stops at structure; math does the range. |
| 6 | 5:35 | Essential, but renegotiate budget or timeline. |
| 7 | 6:50 | 17.36 vs 32.93; coverage 86.7%; caveat. |
| 8 | 8:20 | AI drafts; I keep the loop; build log shows it. |
| 9 | 9:10 | Six checks; evidence and determinism. |
| 10 | 10:00 | Generation 10x, review 1x; gate sets speed. |
| 11 | 11:00 | Zero-fill was worse; null is a question. |
| 12 | 11:45 | Same model, more history. |
| 13 | 12:35 | Same steps, different object. |
| 14 | 13:30 | Shadow, ship one type, measure or stop. |
| 15 | 14:00 | Shipped, tested, honest; review is the job. |

## 10-minute cut

Cut slide 6 and slide 12. If time is still tight, shorten slide 9 and slide 10 to about 45 seconds each. Keep slides 1, 2, 3, 4, 5, 7, 8, 11, 13, 14, 15.
