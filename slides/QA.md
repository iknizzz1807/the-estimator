# The Estimator — Build-Process Q&A

**Panel focus:** how you built the project, how you used AI, and challenges encountered.

This is the main practice file. `QA_EVIDENCE.md` preserves the detailed metrics, architecture, and production answers. `VIBE_CODING_STORY.md` explains the Git-grounded narrative and commit anchors.

Answers are spoken English; Vietnamese notes are not spoken. The Git history was inspected at `C:\Users\Administrator\Documents\GitHub\the-estimator` through `eb8023b`. Code diffs substantiate changes, not every prompt, who suggested an idea, or total hours. Tests and benchmarks were not rerun for this preparation.

## How to practice

- First answer: **20–40 seconds**, then stop. Give detail when they ask.
- Pattern: **goal → bounded task → observed problem → your decision → verification**.
- Start with build events, not model scores. Statistics support the story only when relevant.
- Use your actual personal history. Fill the worksheet in section F before the interview.
- Accept good criticism without turning every answer into a disclaimer.

**Practice first:** 1–6, 9–14, 18, 21, 25.

---

# A. How I built and used AI

## 1. Walk us through how you built it.

> I began with a specification and API contract, before the core implementation. I narrowed the task to extracting scope, preserving unknowns, calculating a range, and asking useful questions. I used coding agents for bounded modules, then integrated the API and UI and worked through deployment and QA findings. After Fest Night, I investigated the extraction path more deeply and corrected a missing-data assumption. I can walk through either the agent workflow or a concrete debugging example.

**Follow-up: stages?**

> October 16 contains the initial scaffold, data, services, API, UI, and early extensions. October 17–19 shows deployment, robustness, and usability improvements. October 23–24 contains the deeper missing-data experiments and correction. Those are commit dates, not a measurement of total hours worked.

**Evidence:** `c0f5cef`, `203974a`, `ee96321`, `d28a7ea`, `12330ff`, `bddd47a`, `f94f78d`.

## 2. What did AI do, and what did you personally contribute?

> Coding agents drafted much of the implementation and tests. I owned the scope, module boundaries, and acceptance decisions: what behavior was required, how the pieces fit, and what the measurements supported. The important distinction isn't that I typed every line. It's that I can explain the behavior, inspect the evidence, and change the approach when working code implements the wrong assumption.

**If they ask whether AI also proposed designs:**

> AI can contribute design options too. I should evaluate and own the choice, not pretend every idea originated with me. I can explain the selected boundaries and trade-offs, and describe the actual suggestions I remember or have saved.

**If they ask for a code percentage:**

> Most of the implementation was AI-assisted, but I didn't measure a reliable line-by-line percentage. I can be specific about the tasks and decisions rather than give a guessed number.

**Nhớ:** Commit author là bạn không chứng minh mỗi dòng do bạn tự gõ, cũng không chứng minh AI làm tất cả. Kể đúng phần việc thật.

## 3. Which tools and models did you use?

> I used OpenCode as the development environment for coding agents. DeepSeek is the extraction provider inside the application. Those are separate roles. The app also supports other providers and an offline stub, so most behavior can be tested without depending on a live API.

**If you cannot verify the exact coding model:**

> I can confirm OpenCode was the coding environment and DeepSeek was the application's extraction provider. For the exact model used in a particular coding session, I'd check the session record rather than guess. The part I can demonstrate here is the task boundary, the resulting change, and its verification.

If you can verify the session model, state its actual name and role. Don't claim the fallback wording if you do know the answer.

**Nhớ:** Không suy ra coding model từ provider runtime. Không tự nhận đã benchmark coding models nếu chưa làm.

## 4. How did you decide what to build first?

> I defined a usable core path: request, structured features, estimate, and follow-up questions. The initial contract made those outputs explicit. An offline extractor let the database, calculation, API, and UI be developed without live-provider availability blocking every iteration. Optional analysis and later refinements could then be added around that core.

**Follow-up: was it the smallest possible MVP?**

> In retrospect, I could have kept the optional experiments smaller and tested the extraction path earlier. The core boundaries helped, but the full project accumulated more review surface than the smallest first pilot would need.

## 5. How did you prompt or constrain the coding agents?

> I used the specification and API contract to make tasks concrete. Extraction had fifteen named fields, true/false/null semantics, source quotes, and explicit negation behavior. API work had a response shape the frontend needed. Separate file ownership bounded parallel implementation. That gave me acceptance criteria to inspect instead of relying on whether a generated app looked plausible.

**If asked what a good task contains:**

> A clear objective, relevant files and interfaces, constraints, acceptance checks, and what must not change. I want the task narrow enough to inspect when it returns.

**Nhớ:** Đây là cấu trúc công việc và artifact thật. Nó không phải nguyên văn một prompt đã được khôi phục từ Git.

## 6. Show us a concrete coding-agent task.

**Prepared answer — reconstruction from a committed change, not a saved prompt**

> I don't have the original prompt here, but I can reconstruct a concrete task from the committed fix. Concurrent estimates could allocate the same project ID and fail on the database constraint. The task is to make allocation and persistence atomic without changing the API contract, and add a regression case for concurrent calls. The patch uses an immediate SQLite transaction with rollback on error. The test launches eight parallel persistence calls and checks unique IDs and the stored count. I can show the diff in commit 1718a8e.

**Task brief to explain or show — explicitly reconstructed, NOT a historical quote**

```text
Fix the project-ID collision in estimate persistence.

Context:
- backend/app/api/state.py: persist_estimate and next_project_id
- backend/tests/test_api.py: persistence/API regression tests
- Concurrent calls can allocate the same P0nn ID before insertion.

Constraints:
- Preserve the existing API response and project-ID format.
- Keep the fix within the current SQLite persistence design.
- Make ID allocation and the associated inserts atomic.
- Roll back on failure and close the connection.
- Do not change estimation or extraction behavior.

Acceptance:
- Add a regression case with eight parallel persistence calls.
- Assert eight distinct IDs and eight stored projects.
- Check that ordinary persistence behavior still works.
- Explain the transaction boundary and remaining limitations.
```

**Follow-up: “Why is that a good AI task?”**

> It names the failure, the relevant code, what must remain stable, and the observable acceptance condition. That makes the change inspectable instead of accepting a broad refactor because the agent says it fixed concurrency.

**Follow-up: “Why an immediate transaction?”**

> Allocation depends on database state. The transaction acquires the write reservation before choosing the next ID, rather than letting competing writers choose it independently. That addresses the observed allocation race; it isn't a claim that every concurrency issue is solved.

**Follow-up: “Did you personally write that exact prompt or run that exact test?”**

> This is a reconstruction of the task from the committed change, not a recovered conversation. The commit contains the implementation and regression test. For the exact original wording or division of work, I would use my actual recollection or saved session rather than infer it from Git.

**Nhớ:** Ví dụ này đầy đủ để giải thích cách giao việc và kiểm tra. Không đổi nhãn “reconstructed” thành “this was my exact prompt”. Nếu nhớ được task thật, thay phần tái dựng bằng lời kể thật của bạn.

## 7. How did multiple agents coordinate?

> The initial decision log records parallel data/database and core-service work with separate file ownership and frozen interfaces. Integration came afterward. Later, QA agents examined backend behavior, frontend integration, and repository hygiene separately. The protection was shared contracts and bounded ownership, followed by integration checks—not assuming independent generated outputs would automatically agree.

**If two agents need to change the same interface:**

> I'd resolve the contract change first and coordinate its consumers. If the work can't be separated safely, doing it sequentially may be faster overall.

**Evidence:** D5 in `c0f5cef`; D16. The second answer describes a working principle, not an invented merge-conflict incident.

## 8. How did you manage context and handoffs?

> The specification, API contract, decision log, and later handoff document keep important state outside any one conversation. They make current behavior, prior decisions, deployment state, and next actions inspectable. The history includes repeated handoff updates, not just a README added at the end.

**If asked about session exhaustion:**

> [Describe your actual session process: what you saved, passed on, and rechecked. Documents support persistent context, but don't establish every detail of your context-window workflow.]

**Evidence:** `e1eb11d`, `e88c1ec`, `d5d2a85`, `4daf23e`, `64b96e6`.

---

# B. Challenges, debugging, and review

## 9. What was the hardest or most instructive challenge?

> The most instructive was realizing that a plausible implementation could encode the wrong assumption. The missing-feature sampler used overall prevalence, but real extraction nulls weren't random missing values. Later review and extraction-path testing exposed that difference. Fixing it meant changing the assumption and evaluation, not just generating better code. It changed how I judge AI-assisted work.

**If asked for a concrete implementation bug instead:**

> The coverage-report bug is a smaller example: local and cloud outputs differed because a nested demo report was being treated as evidence about the main repository.

**Nhớ:** “Most instructive” an toàn hơn khẳng định nó khó nhất nếu trải nghiệm thật của bạn khác.

## 10. Explain the coverage bug and your verification.

> Repository analysis produced different local and cloud risk scores. The local search found a coverage report in a generated demo repository nested inside the checkout. It was valid XML, but described a different repository. The correction checked whether referenced files existed in the analyzed checkout, otherwise returning unknown coverage. The same commit added a regression test and recorded matching local/cloud results after the fix.

**If asked whether AI wrote the exact bug:**

> [Answer from memory.] The Git diff proves the change and regression case, not who generated each original line. I can directly show the failure mechanism and why the correction addressed it.

**If asked whether that guarantees provenance:**

> No. It's a targeted ownership check for the observed failure, not a complete provenance system.

**Evidence:** `d72eec7`, D28, `test_coverage_from_another_repo_is_ignored`.

## 11. Explain the missing-data problem without statistics jargon.

> The request often doesn't mention a feature. I initially sampled those unknowns as though they were features randomly hidden from view. But unmentioned features were much less likely to be present, so the sampler was adding imaginary scope. After review challenged the assumption, I used the rate among extraction-null fields and compared it with the old method and a simple baseline on the same replay.

**Numbers only if asked:**

> Overall presence was about 25%, but only 4.1% of null fields were positive. The old method had MAE 49.64, zero-fill 21.34, and the corrected approach 20.48, with better interval coverage.

**If asked when or who noticed:**

> The deeper experiments were October 23–24, after Fest Night. D31 records external review challenging the assumption. Acting on that feedback, checking it, and implementing the correction were part of the improvement process.

**Evidence:** `3d89142`, `531d8de`, `f94f78d`.

## 12. How do you debug rather than repeatedly ask AI to “fix it”?

> I try to turn a vague failure into a specific mismatch. For the coverage bug, the mismatch was local versus cloud output; tracing the input report explained it. For the prior issue, comparing strategies on the same rows exposed a wrong missing-data assumption. A specific failure gives the coding task a bounded correction and a verification target instead of permission to rewrite unrelated parts.

**If a first fix fails:**

> I'd preserve the reproducing case, check which hypothesis the patch actually tested, and narrow the next change. A changed symptom without an explanation isn't enough reason to accept it.

## 13. How did you review code you didn't manually write?

> I checked the contract, failure behavior, reproducibility, evidence path, tests, and change scope. Important paths included extraction to estimate, invalid effort to rejection, and optional repository failure to a preserved base result. Separate QA passes helped challenge different areas, but their output also needed verification. Reviewing generated code means checking its assumptions and integration, not just reading a success summary.

**Do you understand every line?**

> I don't claim perfect recall of every line. I need to understand critical paths and inspect unfamiliar code before trusting or changing it. I can walk through a relevant module's inputs, transformations, and failure behavior.

## 14. What did the tests catch that mattered?

> Examples include concurrent estimates allocating the same project ID, NaN or Infinity entering actual effort, broken repository analysis discarding useful output, and a coverage report from the wrong repository. Those tests protect real boundaries. But the wrong-prior story shows why tests alone aren't enough: a specified behavior can be implemented correctly while the assumption is unsuitable.

**If asked for the concurrency fix:**

> ID allocation and persistence were moved inside an immediate SQLite transaction, with rollback on error. The regression test uses eight parallel persistence calls and checks unique IDs and stored count. That addresses the observed ID race, not every possible concurrency issue in the app.

**If asked for mutation testing:**

> I can show regression assertions, but I shouldn't claim a systematic mutation-testing run unless I actually performed one.

**Evidence:** `1718a8e`; tests in `backend/tests/test_api.py` and `test_replay.py`.

## 15. Tell us about a deployment challenge.

> A Docker change assumed the cloud build context contained `.git`, as the local checkout did. Render didn't include it, and the hard copy failed. The fix made Git metadata optional so it couldn't block the whole deployment. Later, a best-effort fallback clone supported self-analysis in the cloud. The lesson was to verify environmental assumptions and isolate optional features from the core workflow.

**Why one service?**

> I switched to a static Next.js export served by FastAPI, giving the prototype one deployment and origin. That reduced two-service configuration and integration issues.

**Evidence:** `e0a83d3`, `ab6519c`, `8f1cd42`.

## 16. What did building on a phone change?

> The Android shared filesystem caused frontend build issues around symlinks and native modules. The documented workaround was to build in the Linux root filesystem and copy artifacts back. Heavy dependencies were also unattractive, so I used lighter tools where sufficient. The transferable skill is diagnosing and adapting to constraints, not insisting on a phone-based setup for a team.

**Why did you use the phone?**

> [Give your actual personal reason. The repository records the environment, not your reason for choosing it.]

**Evidence:** D3 and D7; `c88a95c`.

## 17. What did you change for usability, beyond backend correctness?

> The history shows separate iterations for visual design, guidance, tours, sample imports, and editable extracted fields. Users can override features and see the original extraction context rather than silently replace it. There was also a later tour fix to preload an estimate before navigating to that screen. Those are concrete usability improvements, although they are not proof of measured user adoption.

**If asked what user testing you did:**

> [Describe actual observation or feedback you received.] I shouldn't turn UI commits into a claim of formal user research or measured time savings.

**Evidence:** `ee90a07`, `c648dc1`, `894ff5d`, `1c98145`, `fa29570`.

---

# C. Judgment, ownership, and lessons

## 18. What would you do differently if you started again?

> I'd test the real extraction path earlier, keep the simplest baselines visible, and investigate how unknown inputs arise before adding a more elaborate sampler. I'd also keep optional experiments smaller and seek workflow feedback earlier. I'd retain the contracts and module boundaries, because they made it easier to identify which part needed to change.

## 19. Did you reject any AI suggestions or experiments?

> The recorded examples are experiments I didn't turn into supported product claims. PR lead time didn't validate the conversion from repository signals to effort, and some other public-data experiments didn't improve their baselines. I kept the negative results rather than derive coefficients from them. For a literal AI suggestion I rejected, I'd use an actual remembered or saved interaction rather than invent one from the commit history.

**Evidence:** `c1fc8c5`, D26; `docs/PR_LEADTIME_VALIDATION.md`.

## 20. What did AI accelerate, and what remained slow?

> AI helped draft implementations, tests, and revisions. Defining correct behavior, integrating changes, and explaining surprising results still required attention. I didn't measure a reliable ten-times productivity gain; the bars are illustrative. The practical takeaway was to improve review capacity, not simply generate more code in parallel.

## 21. How do you avoid depending on AI without understanding the result?

> I should be able to trace the critical path, reproduce a failure, compare a simpler alternative, and explain why a fix addresses the cause. If I can't, that's a gap to investigate before relying on the code. The missing-prior correction shows why understanding matters: more generation wouldn't solve a specification assumption I hadn't examined.

**If you don't understand a large proposed patch:**

> I'd ask for a smaller change tied to the reproducing case, inspect it, and seek help if needed. Passing tests isn't permission to ship behavior I can't explain.

## 22. How do you keep someone else able to maintain it?

> The specification, API contract, decision log, handoff notes, and regression tests preserve intent and behavior outside a chat session. I'd walk a maintainer through the core path, known failure modes, and demo-only assumptions. A business deployment also needs operational ownership, monitoring, storage and backup, and fallback documentation; a repo link alone isn't a complete handoff.

## 23. What if the simplest solution isn't AI?

> Then I should use the simpler solution. A validation rule, script, SQL query, or spreadsheet improvement may solve the bottleneck with less risk. AI-assisted development and an AI-powered product are different choices. The workflow outcome should determine both.

---

# D. Working with Anduin's team

## 24. How would you work with a non-technical user whose needs are unclear?

> I'd follow a real example from arrival to completion and ask the user to show normal and difficult cases. I'd clarify what output they need, what a costly mistake looks like, and who approves exceptions. Then I'd test a small slice with them, not ask them to specify the technical architecture. Their corrections become examples and agreed rules, not just chat feedback I might forget.

## 25. What would you bring from this project into this role?

> The ability to turn an unclear problem into a working tool with AI, while keeping responsibility for the outcome. I can define interfaces, coordinate implementation, investigate failures, accept review, and change an assumption when evidence contradicts it. At Anduin I'd apply that method to the team's workflow, not assume this estimator is the tool you need.

## 26. Why this role rather than only software engineering?

**Adapt to your genuine motivation.**

> I want to own the loop from understanding the work to building something useful and iterating with users. Engineering helps me implement, but the technology shouldn't become the goal. This role combines business discovery and hands-on building. My data-ingestion and AI-integration experience is relevant, while I'd still need to learn your Digitization Service workflows.

## 27. How would you know a tool is ready for real use?

> We'd need an agreed workflow and owner, approved handling of data, representative acceptance cases, safe review and fallback, and evidence that it helps the process. I'd measure total handling time and quality, including correction and maintenance. Code tests are evidence about behavior, but the workflow owner also needs to agree that the result is usable and the risk is acceptable.

**If asked about the current public demo:**

> It's a prototype, not an approved environment for confidential client documents. Access control, durable storage, provider policy, and stronger release boundaries come before real business use.

---

# E. Panel-style pressure drill

**Panel:** Show us the build process, not product features.

**You:**

> Let me use the coverage bug. Local and cloud results differed, so the score was traced to its source report. The local run was reading a nested demo fixture rather than evidence about the main repository.

**Panel:** What did you change?

**You:**

> A report had to reference files in the analyzed checkout; otherwise the signal became unknown. The commit includes a regression case for the unrelated report.

**Panel:** Where exactly was AI involved?

**You:**

> [Give your actual remembered task and review actions.] I can show the resulting implementation and test; I won't invent a verbatim prompt or assign line-by-line authorship from Git alone.

**Panel:** Are you just reviewing generated code?

**You:**

> Review is one part. I also define the expected behavior and check whether it solves the problem. The missing-prior issue is the difference: correctly implementing the specification wasn't sufficient because the assumption itself needed to change.

**Panel:** Did you find that alone?

**You:**

> External review challenged it, and the later experiments and correction are recorded. Acting on good feedback and verifying the fix is part of ownership, not something I need to hide.

**Panel:** What would you change next time?

**You:**

> Test the actual input path and simplest baseline earlier, before expanding the implementation.

**Nhớ:** Dừng sau mỗi câu trả lời. Follow-up không nhất thiết là bắt lỗi; họ có thể đang kiểm tra bạn thực sự hiểu cách làm việc.

---

# F. Personal-history worksheet — finish before rehearsing

Git cannot reliably fill these for you. Short truthful bullets are sufficient.

1. **Actual coding models inside OpenCode:** verify from saved sessions if available; otherwise use the factual fallback in question 3, not an invented model name.
2. **One real agent task:** question 6 now contains a Git-grounded reconstruction you can explain. Only present it as historical wording if you can independently confirm that wording.
   - Instruction and context: ______
   - Constraints: ______
   - Produced output: ______
   - Your inspection or rejection: ______
   - Verification: ______
3. **Actual work time:** ______ (commit span is not hours worked).
4. **How you managed session/context limits:** ______
5. **Your manual code changes, if any:** ______ (don't invent one to make AI assistance sound acceptable).
6. **Discovery attribution:** what you found ______; what agents/reviewers found ______; how you acted ______.
7. **Real user feedback or informal testing, if any:** ______

Don't read placeholders aloud. If you don't have an exact prompt, say it is a paraphrase and show the artifact you can substantiate.

---

# G. Four evidence tabs, not a repository tour

| Tab | Artifact | Show |
|---|---|---|
| 1 | `git show c0f5cef -- docs/API.md docs/DECISIONS.md` | Contracts and parallel ownership existed at the start |
| 2 | `git show 1718a8e -- backend/app/api/state.py backend/tests/test_api.py` | Real robustness fixes and regression assertions |
| 3 | `git show d72eec7` | Wrong report → targeted fix → test → documented verification |
| 4 | `git show f94f78d`; `docs/ENDTOEND_REPLAY.md` | Later assumption correction and comparative evaluation |

Commands are for the Git repository at `C:\Users\Administrator\Documents\GitHub\the-estimator`. These preparation files are edited in the current Downloads workspace unless you copy them yourself.

For a code walkthrough: **purpose → input → decision → fallback → test**. Stay in one narrow path; do not scroll through the whole repository or run a long benchmark.

---

# H. Small fact card — don't lead with it

| Item | Safe explanation |
|---|---|
| Data | 240 synthetic total, 228 completed, 218 chronological predictions |
| Slide 3 | 258.12 vs 19.25 MAE on final 42; different input information |
| Slide 7 | Recorded-feature MAE 17.36, extracted-feature MAE 20.48, corrected synthetic baseline 18.26 |
| Human superiority | Not established |
| Slide 11 | Wrong prior 49.64; zero-fill 21.34; corrected prior 20.48 |
| 4.1% | Positive among extraction-null cells, not the unknown rate |
| Slide 6 | Model-based probability of exceeding effort budget, not extra days |
| 242 tests | Recorded offline suite; not production certification |
| Timeline | Hybrid design from the start; deeper missing-data research/correction Oct 23–24, after Fest Night |

Detailed metrics, limitations, security, and production questions: `QA_EVIDENCE.md`.

---

# I. Recovery phrases and questions for the panel

If asked something not measured:

> I haven't measured that. I'd check it with [specific test] and use the result to decide [specific action].

If separating implemented behavior from a proposal:

> Let me distinguish what the current implementation does from what I'd add before production.

If memory isn't exact:

> I can explain the task and show the result, but I don't want to reconstruct a literal prompt or exact timeline from memory.

Ask two questions, depending on what they have already explained:

1. **“How do builders here work with workflow owners to define and review a solution?”**
2. **“What are the most common challenges when taking a prototype into daily use?”**
3. **“What would make the first three months successful for this role?”**
4. **“Is there any part of my build process you'd like me to explain more concretely?”**

**Core message:** I use AI to build, understand what it produced, work through failures, and remain responsible for the result.
