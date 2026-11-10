# The Estimator — Technical and Evidence Q&A Appendix

Secondary preparation for the AI Business Operations Associate presentation. Start with the build-process questions in `slides/QA.md`.
Vietnamese notes are preparation notes, not spoken answers.

This playbook is grounded in the repository and recorded reports. The benchmarks and test suite were not rerun while preparing it. No answer guarantees an interview outcome. For personal motivation or development history, use only what is true for you.

## How to practice

- Learn the argument, not every word. First answer: 20–40 seconds. Stop and let the panel choose the next direction.
- Structure: **answer directly → one piece of evidence → decision or next step**.
- Distinguish **implemented**, **measured on synthetic data**, and **proposed for production**.
- Don't recite every caveat on every question. State the one that changes the answer.
- If challenged, explain the boundary calmly. You don't need to defend every prototype choice forever.
- For hypothetical numbers, say **“for example”** or **“we would agree that threshold with the team.”**

### Learn these first

Use this appendix when asked about evaluation, architecture, metrics, or production. It is not the main presentation narrative. The panel's stated focus is how the project was built, how AI was used, and the challenges encountered.

## Metric card — know this without looking

| Number | Exact meaning |
|---|---|
| 240 | Total synthetic projects, seed 42 |
| 228 | Completed projects; 12 are open |
| 218 | Walk-forward predictions after 10 initial training rows |
| 258.12 / 19.25 | LLM-only / recorded-feature estimator MAE on the same final 42 replay steps |
| 35.27 | LLM-with-recent-history MAE on those 42 steps |
| 17.36 / 86.7% | Recorded-feature estimator MAE / interval coverage on all 218 steps |
| 32.93 / 18.26 | Raw biased / de-biased synthetic-team MAE on the full replay |
| 49.64 / 55.5% | Wrong marginal-prior extraction-path MAE / coverage |
| 21.34 / 74.3% | Zero-fill extraction-path MAE / coverage |
| 20.48 / 85.3% | Conditional-prior extraction-path MAE / coverage |
| 25.2% | Marginal feature-positive rate in the completed extraction corpus |
| 4.1% | Positive among extraction-null cells: 100 / 2,436, NOT the unknown rate |
| 71.2% | Approximately the share of unresolved feature cells in that corpus |
| 17.99 | Conditional-prior MAE after five **oracle** answers per step |
| 0.933 | Positive-feature micro-F1 on 236 evaluated synthetic emails; four skipped |
| $0.20 | Approximate extraction-batch cost, estimated from tokens/pricing, not an invoice |
| 242 | Recorded passing offline-test count; not production certification |
| 46% / 63% / 91% | Model-estimated probability of effort exceeding a 100-person-day budget |

Units: **person-days of effort**, not calendar delivery time. MAE is a mean, not accumulated error. The model's internal `method="point"` label does not mean all prediction uncertainty disappears.

---

# A. The questions most likely to test your credibility

## 1. Is your data real or synthetic?

**Answer**

> It's synthetic. I didn't have access to real company effort history, so I generated 240 reproducible projects with known features and outcomes. That let me test the pipeline, extraction errors, missing information, and the learning mechanism. It does not establish accuracy on real client projects. The next validation would use reviewed company history or a shadow-mode pilot.

**If they ask how it was generated**

> Actual effort comes from multiplicative feature effects, a few interactions, lognormal noise, outliers, and a time-based drift. Emails are template-generated, with omissions and explicit negations. The synthetic team estimate is deliberately biased low.

**If they ask whether Ridge was favored**

> Yes, the main-effects structure is favorable to log-linear regression. That's a limitation of the experiment. The model doesn't read the hidden formula file, but that alone doesn't make the benchmark independent of my design assumptions.

**Nhớ:** Nói “synthetic” ngay, không né bằng “realistic data”. Ground-truth separation không giải quyết hết circularity.

Evidence: `docs/DATA_GENERATION.md`, `docs/DECISIONS.md` D4, D13.

## 2. Does the system actually outperform a human estimator?

**Answer**

> I haven't established that. The baseline is simulated, not a study of human estimators. Its raw MAE is 32.93, but after correcting its systematic bias it is 18.26. My extracted-feature pipeline is 20.48. So I wouldn't recommend adoption on an accuracy-superiority claim. I'd test whether it improves the overall workflow: handling time, consistency, missing-information detection, and review quality.

**If they say those benefits are also unproven**

> Correct. They're pilot hypotheses, not benefits I've measured yet. The delivered evidence is a working pipeline and controlled evaluations. A real pilot would determine whether the operational benefits justify using it.

**Nhớ:** Không biến auditability thành lý do tự động adopt. Nó cũng phải tạo giá trị và không tăng gánh nặng.

Evidence: `docs/BASELINE_COMPARISON.md`, `docs/ENDTOEND_REPLAY.md`.

## 3. Then why does your slide say “half the team's error”?

**Answer**

> That headline describes the raw synthetic comparison: 17.36 versus 32.93. It is too broad without the baseline qualification. The more useful comparison includes the corrected baseline and the extraction path. I should have made that distinction explicit on the slide; that's why I state it in the presentation. I don't interpret the headline as a claim about real human performance.

**Nhớ:** Nhận đúng lỗi framing một lần rồi đi vào evidence. Không đổ lỗi cho slide, tool hay AI.

## 4. Why is the error 19 on one slide and 17.36 on another? Is 258 a total?

**Answer**

> They are mean absolute errors on different windows. The 19 is rounded from 19.25 on the final 42 walk-forward steps. The 17.36 is on all 218 steps. The 258.12 is also MAE, for the LLM-only baseline on the same final 42. It is not a total error or the error from one prompt.

**If they ask whether the comparison is fair**

> It's not an equal-input end-to-end comparison. The estimator uses recorded features there, while the LLM reads emails with omissions. It measures those configurations, not the isolated superiority of regression over an LLM. The separate extraction-path replay exposes that additional error.

Evidence: `docs/AB_MEASUREMENT.md`.

## 5. How did you prevent data leakage?

**Answer**

> The outer replay sorts projects by date and ID. At each step, it trains on earlier rows and predicts the next one. In the conditional-prior experiment, the null prior is also estimated from earlier rows. The LLM-with-history baseline sees only earlier projects. However, chronological training doesn't remove every evaluation limitation: I developed and compared design choices on the synthetic benchmark, so I wouldn't call it an untouched external test.

**If they ask about the deployed prior**

> The demo loads a prior file built from completed history. That's appropriate for estimating a new request after that history, but I wouldn't reuse that full-history file to claim leakage-free historical evaluation. The conditional-prior replay computes its own past-only priors.

**If they ask about real timestamps**

> In production I'd split by when information became available, not simply project creation date. Features must be frozen as known at estimation time, and training outcomes must already be completed and available.

**Nhớ:** Không nói “absolutely no leakage, proven” chỉ vì không đọc `ground_truth.json`. Outer split, tuning, and feature availability là ba vấn đề khác nhau.

Evidence: `backend/scripts/endtoend_null_prior.py`, `backend/scripts/build_null_prior.py`, `docs/AB_MEASUREMENT.md`.

## 6. Walk me through the mistake on slide 11.

**Answer**

> The first Monte Carlo implementation sampled unresolved features using their overall prevalence, about 25%. But extraction nulls meant “not mentioned,” not randomly hidden. Only 4.1% of those null cells were actually positive. The wrong prior invented too much scope and gave 49.64 days MAE, worse than zero-fill at 21.34. Using a null-conditioned prior reduced MAE to 20.48 and increased coverage to 85.3%.

**If they point at “4.1% unknown”**

> The label is shorthand that should be more precise: 4.1% positive among unknown fields. Around 71% of the cells were unknown. Those are different denominators.

**If they ask why you didn't just use zero**

> Zero-fill was a strong simple baseline. The conditional sampler improved MAE only modestly, but coverage rose from 74.3% to 85.3%. For risk-based decisions, that coverage difference matters. Whether it justifies the extra complexity still depends on the actual workflow.

Evidence: `docs/ENDTOEND_REPLAY.md`, `docs/DECISIONS.md` D31.

## 7. Why did your earlier experiment suggest the wrong approach was good?

**Answer**

> It simulated random masking. Under that mechanism, overall feature prevalence is a sensible prior. Real extraction nulls were caused by what the email didn't mention, which is a different mechanism. Both experiments describe their own setup, but only the extraction-path experiment reflects the deployed missingness. I learned to validate the data mechanism, not just the algorithm.

**Nhớ:** Không nói “Monte Carlo was wrong”. Sai là prior và experiment assumptions, không phải sampling tự nó.

Evidence: `docs/MC_ABLATION.md`, `docs/ENDTOEND_REPLAY.md`.

## 8. What did you personally do if AI wrote most of the code?

**Answer**

> I owned the system boundaries, interface contracts, acceptance criteria, and evaluation decisions. Coding agents drafted implementations around those contracts. My responsibility was to check integration and decide what the evidence supported. A concrete example is the missing-data prior: the implementation ran, but the extraction-path evaluation showed that the assumption was wrong. I changed the approach rather than accept working code as a working solution.

**If they ask for the literal prompt or author of a specific line**

> I can show the contract, implementation, and evaluation artifact. I don't want to invent a verbatim prompt or claim authorship from memory. I can explain what the code does, what constraints it implements, and why I accepted or changed it.

**Nhớ:** Dùng “AI-generated” cho một bug cụ thể chỉ nếu bạn thật sự biết nguồn gốc của nó. Biết giải thích code và quyết định quan trọng hơn nhận công viết tay mọi dòng.

## 9. Give me one concrete example of how you reviewed AI-assisted work.

**Answer**

> One documented integration bug involved codebase coverage. The analyzer searched subdirectories and picked up a coverage report from a generated demo repository inside the project. That made the local and cloud risk scores disagree. The fix checked that the report actually referenced files in the analyzed checkout, otherwise treating coverage as unknown. A regression test was added. The key review question was whether the evidence belonged to the object we were scoring.

**If they ask whether that solves every coverage-ownership problem**

> No. It's the implemented regression fix, not a complete provenance system. I'd strengthen ownership checks if this signal became business-critical.

**If they ask for the evidence**

> It's decision D28 and the test `test_coverage_from_another_repo_is_ignored` in `backend/tests/test_codebase.py`.

**Nhớ:** Đây là incident có log và test, không phải câu chuyện prompt giả định. Chỉ kể trình tự tương tác với AI nếu bạn nhớ thật.

## 10. What do 242 tests actually prove?

**Answer**

> They are the recorded offline suite covering services and API behavior: extraction, estimation, replay, question ranking, packages, data validation, and codebase analysis. They provide regression protection for implemented behaviors. They don't prove production readiness, live-provider reliability, or business value. Those require separate integration, security, operational, and user validation.

**If they ask whether AI-generated tests can share the implementation's mistakes**

> Yes. That's why I also use simple baselines, end-to-end experiments, and checks against known outcomes. A test that repeats the implementation's assumption isn't independent evidence that the assumption is valid.

**Nhớ:** Không gọi 242 tests là code coverage, 242 user scenarios, hay 242 live LLM tests.

Evidence: `backend/tests/`, `docs/DECISIONS.md` D28–D31.

---

# B. Architecture and technical judgment

## 11. Explain the architecture without technical jargon.

**Answer**

> The language model reads the request and organizes it into a checklist, with source text to review. A separate calculator uses past projects to estimate effort and uncertainty. Missing information becomes follow-up questions. The user can compare scope options, and completed work can feed the next model update. The goal is a reviewable first pass, not an automatic commitment to the client.

## 12. Why Ridge, intervals, and Monte Carlo? Is this overengineered?

**Answer**

> They address different problems. Ridge provides a regularized effort estimate from a small feature set. Residual-based intervals represent prediction error. Monte Carlo represents uncertainty about missing features. I compared simpler alternatives rather than assume the extra components helped. Zero-fill, for example, remained an important baseline. In a new workflow I'd start simple and keep each component only if it adds measured value.

**If they ask why log effort**

> Effort is positive, and feature effects can be multiplicative. A log target supports that structure and maps the prediction back to positive effort. But the synthetic generator also favors that structure, so I wouldn't assume it is best on real data.

**If they ask about more powerful models**

> In the recorded-feature replay, the deployed Ridge variant had MAE 17.36, while the tested boosted models were around 25. More flexibility didn't help on this small synthetic dataset. That result guides this prototype, not every future dataset.

Evidence: `docs/BASELINE_COMPARISON.md`, `backend/app/services/estimation.py`.

## 13. Does “P10–P90” guarantee that 80% of projects will fall inside?

**Answer**

> No. It expresses the intended predictive interval, and I measure its empirical coverage. The deployed method uses out-of-fold residual quantiles with a tuned tail widening; it isn't a textbook split-conformal implementation. Under drift I wouldn't claim a formal coverage guarantee. I would monitor coverage together with interval width and performance across relevant project groups.

**If they say a very wide interval also covers**

> Exactly. Coverage alone isn't usefulness. I'd compare width, error, and whether the interval changes a decision. An interval too wide to guide scope or review may have little operational value.

**Nhớ:** Prediction interval, không phải confidence interval cho mean. Aggregate coverage không đồng nghĩa coverage tốt trên mọi subgroup.

## 14. Why 2,000 Monte Carlo draws? What about correlated features?

**Answer**

> Two thousand is the prototype's fixed sampling budget, with a fixed seed for repeatability. I haven't established it as an optimal number. The current sampler also treats unresolved features independently. That is a simplifying assumption; real features may co-occur. I'd check numerical stability and compare joint or conditional approaches on real history before relying on it for high-stakes decisions.

**If they ask whether the ablation solved correlations**

> No. The synthetic features were generated independently. Local and donor-based variants didn't improve that experiment, but it doesn't establish that independence is safe for real project data.

## 15. What happens when every question is answered? Does uncertainty disappear?

**Answer**

> Uncertainty about those input features disappears, but uncertainty about effort does not. The model still returns a residual-based interval. The internal method label switches from Monte Carlo to “point,” but that means a fixed feature vector, not perfect certainty about the outcome. I would make that naming clearer in a production interface.

**Nhớ:** Tránh lặp lại câu README “trả lời hết thì thành point estimate” theo nghĩa P10=P50=P90.

Evidence: `estimate_mc` delegates to `estimate` when no unknowns remain; both in `backend/app/services/estimation.py`.

## 16. How do you know the LLM hasn't invented evidence?

**Answer**

> I ask for verbatim source quotes and check them against the email using fuzzy matching. But the current check is not a hard evidence gate: if a quote fails, it is removed and confidence is reduced while the feature value remains. Also, a real quote can still be misinterpreted. For a production financial workflow, unsupported or ambiguous values should be held for review before affecting downstream decisions.

**If they ask why you didn't enforce that already**

> It is a remaining prototype limitation. The warning made issues visible, but a stronger release boundary would block unsupported values. I'd prioritize that before using the system for real commitments or financial records.

**Nhớ:** Thẳng nhưng không hạ thấp toàn bộ app. “Review aid currently; stricter gate before production.”

Evidence: `_verify_evidence` in `backend/app/services/extraction.py`.

## 17. What does extraction quality 0.933 mean?

**Answer**

> It's micro-F1 for detecting positive features against recorded labels, pooled across the successfully evaluated emails. It combines precision and recall; it isn't the percentage of all fields that are correct. Precision was about 98.6% and recall about 88.6%. Four of 240 emails failed after retry and were excluded from that score. I'd report those failures alongside F1 in any operational evaluation.

**If they ask whether omitted features should count as misses**

> This metric compares against actual feature presence, so an omitted positive feature counts as a miss even when leaving it unknown is the right extraction behavior. The report separately measures whether omitted features remain unknown and whether explicit negations are handled correctly. Those metrics answer different questions.

Evidence: `docs/EXTRACTION_EVAL.md`.

## 18. How do you choose the next question? Is it really value of information?

**Answer**

> For each unresolved feature, I calculate P50 once with it present and once with it absent, then rank the absolute difference. The top five become questions. It's a simple sensitivity ranking, not a full expected-value-of-information calculation. It doesn't yet account for the chance of each answer, the cost of asking, or whether the answer changes the user's decision.

**If they ask about other unknowns**

> They are held at zero in both scenarios. That's a documented simplification. A richer ranking could integrate over the other unknowns and prioritize questions by decision impact.

Evidence: `backend/app/services/voi.py`.

## 19. What if a user gives the wrong answer or overrides the extractor?

**Answer**

> The application accepts user overrides and labels them in the UI while preserving the original extraction context. But a user answer isn't automatically true just because it is human-provided. In a team workflow I'd define who can approve corrections, record who changed what and why, and avoid training on unreviewed labels. Review ownership matters as much as the input mechanism.

**Nhớ:** UI override labeling có thật; approval roles, immutable audit history và quality-gated labels là đề xuất, không phải đã implement đầy đủ.

Evidence: `docs/DECISIONS.md` D29; `apply_answers` in `backend/app/api/state.py`.

## 20. How does the model learn when actual effort arrives?

**Answer**

> The actual-effort endpoint records the outcome and retrains Ridge on the available usable history. There is also a separate sliding-update artifact to show coefficient changes in the UI; that display calculation is not itself the Ridge learning algorithm. In production I'd add reviewed data admission, model versioning, and a release gate before replacing a model used for business decisions.

**If they ask whether the null prior also updates automatically**

> Not through that same learning loop. The demo loads the null-prior artifact built by a separate script. Rebuilding and monitoring that artifact would need to become an explicit production process.

Evidence: `apply_actual` in `backend/app/api/state.py`, `backend/app/services/learning.py`, `backend/scripts/build_null_prior.py`.

## 21. What is Codebase Lab, and why isn't it central to the presentation?

**Answer**

> It's an optional risk-explanation layer using repository history and Python code signals. It can widen or adjust the estimate, but the conversion from those signals into person-days still uses demo assumptions. I kept the presentation focused on the more transferable extraction, review, and evaluation loop. I don't want repository-risk experiments to look like a validated effort model.

**If they ask what was measured**

> Studies on public commits support some relationships with change size and similar-change retrieval. They do not establish a reliable mapping from repository friction to person-days. I also recorded failed validation attempts rather than derive product coefficients from them.

**If they ask whether it supports any repository**

> The current analysis is scoped to Python-dominant repositories. Unsupported repositories should degrade with an explanation while preserving the base estimate.

Evidence: `docs/SURCHARGE_CALIBRATION.md`, `docs/DECISIONS.md` D20–D28.

---

# C. Adoption, security, and business operations

## 22. Why should we adopt this if it doesn't beat the corrected baseline?

**Answer**

> I wouldn't ask you to adopt it on the current evidence. I'd propose a small shadow-mode pilot: the team keeps its existing decision process, and the tool produces a parallel first pass. We measure total handling time, corrections, missed requirements, and decision quality. If it saves effort without unacceptable errors or review burden, we have a reason to continue. If not, we simplify or stop.

**If they ask what would make you kill it**

> No meaningful handling-time benefit, critical errors, or additional review work that outweighs the saved effort. We'd agree the thresholds and sample before the pilot, based on the cost of mistakes.

**Nhớ:** Đây là cách trả lời “business-first” mạnh nhất. Không cần cứu model bằng mọi giá.

## 23. How would you measure ROI?

**Answer**

> I'd measure total human handling time before and during the pilot, including review, correction, and exceptions. Then compare labor capacity released with model, infrastructure, and maintenance costs. Quality is a release constraint, not something to trade away for a faster average. I would separate capacity savings from actual cash savings unless there is a clear business mechanism connecting them.

**If they want a formula**

> A starting model is volume times the reduction in handling time times loaded labor cost, minus operating and maintenance costs. I'd segment by document complexity and use comparable cases so an easier pilot batch doesn't create a fake improvement.

## 24. What if Anduin has only 20 completed examples?

**Answer**

> I wouldn't start by promising a learned effort model. I'd first structure the input, add deterministic checks, and support human review. Twenty examples may help discover the schema and common exceptions, but they provide limited evidence for reliable prediction. I'd capture reviewed outcomes and compare simple baselines as history grows. The first useful tool may not need statistical prediction at all.

**Nhớ:** Model chạy được với 5–10 rows không đồng nghĩa đủ dữ liệu để tin trong business.

## 25. How would you handle confidential financial documents?

**Answer**

> Before sending any document to a model, I'd confirm the company's approved processing boundary: providers, contracts, retention, access, and logging policies. I'd minimize the data sent, keep sensitive content out of unnecessary logs, and use approved storage and access controls. If external processing isn't allowed, I'd evaluate approved private options or a non-LLM approach. The public demo is not a secure environment for client documents.

**If they ask whether a local model guarantees safety**

> No. Local deployment changes the data boundary, but access control, retention, logs, backups, and model quality still need evaluation.

**Nhớ:** Không tuyên bố SOC 2, GDPR compliance, encryption, zero retention hay RBAC đã có nếu chưa kiểm chứng.

## 26. Is the current app production-ready? What would you fix first?

**Answer**

> It's a deployed prototype. Before real business use, I'd prioritize secure access and durable storage, a hard review boundary for unsupported outputs, approved provider handling, and operational monitoring. The public API currently lacks authentication and rate limiting, and the demo storage on Render is ephemeral. I'd also separate demo data from real workflow records and version estimates so we can reconstruct decisions.

**If they ask about prompt injection**

> I'd treat the document as untrusted data, validate the output schema, restrict downstream actions, and test adversarial instructions embedded in documents. Structured output helps but isn't a complete defense. I haven't established a comprehensive prompt-injection defense in this prototype.

**Nhớ:** Chọn top risks theo deployment boundary; không đọc một shopping list công nghệ.

Evidence: `README.md` limitations, `docs/DECISIONS.md`, extraction implementation.

## 27. How would you find the first problem worth solving here?

**Answer**

> I'd sit with the people doing the work and follow a request from arrival to completion. I'd look for repeated copying, waiting, rework, and exceptions, then quantify their frequency and cost. I'd check existing tools before proposing a new one. I'd choose a narrow workflow with a willing owner, accessible data, measurable outcomes, and manageable risk—not simply the most interesting AI problem.

**If they ask what you need from the team**

> A workflow owner, examples of normal and difficult cases, clarity on what mistakes cost, and time with the people who will use the result. Technical access comes after we understand that boundary.

## 28. What if the team doesn't use your tool?

**Answer**

> I'd observe where it creates friction rather than assume the team needs more training. Does it duplicate data entry, interrupt their existing tools, or create more exceptions than it resolves? I'd build with a small user group, test real tasks, and watch total handling time and repeat use. Adoption is evidence that the workflow fits, not just that the interface looks good.

**If they say the existing process is “good enough”**

> Then the burden is on the new tool to justify switching. If the improvement is marginal and the transition cost is high, leaving the process alone may be the right decision.

## 29. What happens if the model or provider fails?

**Answer**

> Extraction retries and, if it still cannot produce usable output, returns unknown fields with a warning. Missing credentials can select an offline stub, which must be clearly labeled. Optional repository analysis also degrades without discarding the base estimate. For real operations I'd define an explicit manual fallback and make degraded mode visible, so users don't confuse availability with reliable output.

**If they ask whether all-null output should still generate a quote**

> I wouldn't treat it as ready for a commitment. It should trigger review or manual handling. The ability to return a number isn't sufficient reason to show it as actionable.

**If they ask about latency**

> The recorded extraction evaluation averaged about 3.3 seconds per successful email. That's not a production latency SLA. Refinement currently reruns extraction, so caching stable extraction results is an obvious improvement after correctness and security.

Evidence: `docs/EXTRACTION_EVAL.md`, `docs/DECISIONS.md` D21, D29; extraction service.

## 30. A reviewer says your answer is wrong. What do you do?

**Answer**

> First I'd ask them to show the case and explain the expected result. I'd separate an extraction mistake, a missing business rule, a disputed definition, and an incorrect model assumption. We'd correct the immediate case safely, then decide whether the fix is a rule, a schema change, better evidence handling, or more training data. I'd add a regression case so the same issue becomes easier to catch next time.

**If they ask whether you always accept the reviewer**

> No. If the definition is ambiguous, I'd resolve it with the workflow owner. Consistent labels matter; silently treating every correction as truth can make the system worse.

---

# D. Role fit, ownership, and pressure questions

## 31. Why this role rather than a pure software engineering role?

**Suggested answer — adapt to your actual motivation**

> My engineering background helps me build, but the part I want to own is the full loop: understand a workflow, identify where effort is being wasted, build the right-sized solution, and see whether people benefit. This role explicitly combines those responsibilities. I'd still write code, but success would be an improved business process, not the sophistication of the stack.

**If they ask for relevant experience from your CV**

> At Visual Hive, I worked on ingestion and data-cleaning workflows, including schema mapping. That's relevant because a working tool has to handle messy inputs and fit how people use data. My current private-credit work also gives me exposure to financial-document reasoning, while I would still need to learn Anduin's specific workflows.

**Nhớ:** Không tự bịa adoption numbers, revenue impact hay measured time savings từ CV. Nêu đúng phần bạn trực tiếp làm.

## 32. Why Anduin, and what would make you useful here?

**Suggested answer — keep only what you genuinely believe**

> What interests me is the combination of a real financial workflow and a team explicitly looking for practical builders. My experience includes messy-data pipelines, AI integration, and financial-document work. I can bring those skills while learning the actual Digitization Service process. I would aim to become useful through one well-chosen improvement, not arrive assuming my existing architecture is the answer.

**Nhớ:** Tránh trích company scale numbers vì context có nhiều mốc khác nhau. Hiểu business quan trọng hơn thuộc marketing stats.

## 33. What would you do differently if you started again?

**Answer**

> I'd test the extraction path earlier, establish the simple baselines first, and define the missing-data mechanism before implementing a more elaborate sampler. I'd also seek real user feedback earlier. That would reduce the risk of building sophistication around the wrong assumption. I'd keep the separation between language interpretation and calculation, because it made failures easier to diagnose.

**Nhớ:** Một thay đổi cụ thể + lý do. Không nói “everything” hoặc chỉ “better prompts”.

## 34. How do you know when to stop building? What if we ask for a simpler solution?

**Answer**

> I'd stop when the agreed outcome is met or the next feature doesn't justify its cost and risk. If SQL, validation rules, or a spreadsheet solves the problem well enough, I'd use that. In this project, I'm willing to keep a simple baseline or remove an optional component if it doesn't improve the workflow. The business problem earns the complexity; the technology doesn't.

**If they ask about a two-day deadline**

> I'd narrow the output and risk boundary first: one input type, one user task, visible exceptions, and human approval. I'd cut optional features before cutting the checks that prevent a misleading result.

## 35. Why should we hire you?

**Suggested answer**

> I bring the ability to turn an unclear problem into a working tool, and the discipline to check whether the tool deserves to be trusted. This project shows both: I shipped an app, separated AI interpretation from calculation, and changed an implementation when the evidence contradicted it. With your team, I'd apply that ownership to the workflow that matters most—not insist on using this particular solution.

**Nhớ:** Không thêm “I'm the perfect fit” hoặc lời hứa chưa chứng minh. Cho họ bằng chứng để tự kết luận.

---

# E. Rapid-fire follow-ups

### “Five identical runs prove calibration is the problem, right?”

> No. They show stability on that one sample. The cause of error needs separate analysis; repeated agreement doesn't establish correctness.

### “Why not just give the LLM past projects?”

> I tested a recent-history prompt. Its MAE was 35.27 on the final 42 steps, compared with 258.12 without history and 19.25 for the recorded-feature estimator. History helped substantially. The estimator comparison still has the input-information caveat, so it isn't proof that no better LLM approach could work.

### “Why not a vector database or agents everywhere?”

> The main task has a fixed schema and a compact numeric history. Extra orchestration or storage should solve a demonstrated need. I chose a smaller deployment and would add retrieval or agents only if the workflow and evaluation justified them.

### “Why DeepSeek?”

> It was the selected extraction provider, with measured quality and a low estimated batch cost in this experiment. The service supports other providers and an offline stub. For Anduin, approved data handling and measured task quality would come before carrying over my demo choice.

### “Why build on a phone?”

> That was my available build environment. It encouraged bounded tasks and a lightweight deployment. It's context, not the main accomplishment; the useful part is the working result and how I verified it.

### “How long did you build, and how much AI did you use?”

> [Give your actual timeline and usage. The decision log records build and evaluation work across October 16–24, but that doesn't establish total hours, exact coding proportions, or a complete development timeline. Don't invent those numbers.]

### “Can you promise the estimate improves with every completed project?”

> No. More data can help, but noisy labels, changed scope definitions, or drift can hurt. I would monitor performance and review model changes rather than assume every retrain is an improvement.

### “Shouldn't an answered question always narrow the range?”

> Not necessarily in absolute width. An answer can reveal higher scope and move the estimate upward. I wouldn't promise monotonic narrowing for every answer. We should distinguish resolving input uncertainty from changing the effort distribution.

### “The 46% risk sounds precise. Can I trust it?”

> It's a model-based approximation from a lognormal fit to the estimated interval, not a validated real-world frequency. I'd use it to support a risk discussion, not treat the precision as a guarantee.

### “How can you remove mobile if the client asked for mobile?”

> I can't make that business decision for them. The package is a scenario for phasing scope; it needs client agreement. I'd add explicit must-have and negotiable constraints before treating package generation as a recommendation workflow.

### “Is 95 person-days a promise to finish in 95 days?”

> No. Effort and elapsed time are different. A delivery date also depends on staffing, dependencies, availability, and parallelism. This prototype doesn't establish a scheduling model.

### “Are the feature multipliers causal?”

> No. Learned coefficients describe associations within the training data and model. I wouldn't interpret changing a feature as a proven causal intervention on real effort.

### “What if the request doesn't fit your 15 features?”

> The taxonomy is a real limitation. Unmodeled requirements can affect effort without appearing in the feature vector. I'd make out-of-scope requests visible and route them to review, then expand the schema only with clear definitions and validation. I wouldn't claim the current extractor understands every software project.

### “Can we deploy this to our team tomorrow?”

> We can inspect or demonstrate it with non-sensitive examples. I wouldn't put live client documents or business commitments through the public demo. I'd first agree access, storage, provider policy, review boundaries, and a narrow pilot.

---

# F. A panel-style pressure drill

**Panel:** Your end-to-end model is worse than your corrected baseline. Why spend more time on it?

**You:**

> Only if there is a workflow benefit worth testing. I'd time-box a shadow pilot rather than argue for adoption from model accuracy.

**Panel:** You haven't measured that workflow benefit either.

**You:**

> Correct. That's why it's the next experiment, not a result I claim. I'd first establish a handling-time and quality baseline with the users.

**Panel:** Why not just improve the existing spreadsheet?

**You:**

> That may be the better answer. I'd compare it. The goal is a better process, and the smallest effective change should win.

**Panel:** Then what does your project demonstrate?

**You:**

> That I can ship a working system, make its assumptions inspectable, and revise the approach when measured results disagree. It demonstrates how I build and evaluate—not that this exact estimator should be deployed at Anduin.

**Panel:** What would give you confidence to release a tool here?

**You:**

> A clearly owned workflow, approved data handling, agreed quality thresholds, observed benefit on representative cases, and a safe review and fallback process. I'd make that a joint release decision with the workflow owner.

**Ghi nhớ:** Sau câu trả lời, dừng. Đừng thêm ba disclaimer vì sợ họ chưa tin. Calm ownership thuyết phục hơn defensive overexplaining.

---

# G. When you don't know

### A fact you have not measured

> I haven't measured that, so I don't want to give you a number. I'd test it by [specific test], and use [metric or threshold] to decide.

### An internal workflow you haven't seen

> I don't know your current workflow well enough to choose that yet. I'd first clarify [owner, error cost, data boundary, or bottleneck].

### A weakness you genuinely agree with

> That's a fair limitation. The current implementation does [actual behavior]. Before using it for [business consequence], I'd change [specific boundary] and verify it with [test].

### A question whose premise may be wrong

> Can I clarify whether you mean [A] or [B]? They would lead to different decisions.

### You need a moment

> Let me separate the current behavior from what I'd propose for production.

**Avoid:** “It should be fine,” “AI handled that,” “It's production-ready because tests passed,” and “I would just use a better model.”

---

# H. Good questions to ask the panel

Choose two or three, depending on what they have already explained.

1. **“Which part of the Digitization Service workflow currently creates the most manual rework or exceptions?”**
2. **“What would make the first three months successful for someone in this role?”**
3. **“How do builders and workflow owners currently agree quality requirements and decide when a tool is ready to use?”**
4. **“What existing tools or approved AI capabilities would you want a new team member to build on rather than replace?”**
5. **“Is there anything in my approach today that you'd like me to clarify or examine more critically?”**

---

# I. Final rehearsal checklist

- [ ] Answer 1, 2, 4, and 6 without mixing a denominator or metric.
- [ ] Explain your personal contribution in answer 8 with only truthful attribution.
- [ ] Open the D28 test and end-to-end report so you can show evidence quickly.
- [ ] Explain a business pilot without promising unmeasured savings.
- [ ] Answer “Why this role?” in your own words, not only engineering language.
- [ ] Practice the pressure drill without becoming defensive.
- [ ] Stop each initial answer within roughly 40 seconds.
- [ ] Have two questions ready for the panel.

**Core message:** I can build quickly with AI, understand what the evidence actually supports, and stay responsible for whether the result helps the business.
