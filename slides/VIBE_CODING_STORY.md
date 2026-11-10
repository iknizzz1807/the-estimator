# Câu chuyện build The Estimator — dựng lại từ Git history

## Nguồn và giới hạn

Đã đọc lịch sử commit ở `C:\Users\Administrator\Documents\GitHub\the-estimator` tới `eb8023b`, và kiểm tra diff các mốc quan trọng: scaffold/contract, API robustness, deployment, coverage bug, conditional prior.

- **Git xác nhận:** thứ tự thay đổi được commit, code/test/document nào xuất hiện, những gì commit message và decision log ghi lại.
- **Git không tự xác nhận:** nguyên văn prompt, model coding từng phiên, ai đề xuất ý tưởng đầu tiên, ai gõ từng dòng, tổng giờ thực làm, cảm xúc hay suy nghĩ của bạn.
- Author của mọi commit là tên của bạn không đồng nghĩa mọi dòng được viết thủ công. Commit lớn cách nhau vài phút cũng không chứng minh sản phẩm được nghĩ ra và viết từ đầu trong đúng số phút đó.
- History có cả timestamp UTC và +07. Khi kể, dùng các giai đoạn và thứ tự commit; không suy ra giờ làm từ timezone hay khoảng cách commit.
- Đây là retrospective dựa trên artifact. Chỉnh cách xưng “tôi quyết định/tôi phát hiện” cho đúng trải nghiệm thật của bạn.

## Luận điểm mạnh nhất

**Bạn không bắt đầu bằng một prompt rồi nhận nguyên app. History cho thấy specification và contract trước, implementation theo module, integration và QA sau, rồi thêm những vòng sửa cả code lẫn giả định.**

Đây là câu chuyện hợp với yêu cầu panel hơn một bài nói chứng minh model có MAE đẹp.

---

## 1. Bạn thiết kế giao việc trước khi sinh code

### Bằng chứng

- `c0f5cef` — scaffold, specification, API contract, canonical feature set, decision log.
- D5 có ngay ở commit đầu: hai agent triển khai data/database và core services với separate file ownership, dùng chung interface.
- Tiếp theo là `203974a` data generator, `ee96321` database, `d28a7ea` core services.
- `12330ff` nối API; `bddd47a` thêm frontend.

### Ý nghĩa để kể

Điểm đáng nói không phải số dòng AI viết. Bạn có thể cho panel thấy công việc đã được **biến thành những phần có đầu vào/đầu ra rõ ràng**, để agent không tự thiết kế hai interface khác nhau rồi bắt bạn chữa ở cuối.

Một boundary cụ thể:

- Extraction: 15 feature names, true/false/null, quote và warning.
- Estimation: feature vector vào, quantiles ra.
- API: response shape dùng chung với frontend.

### Câu nói có thể dùng

> “The first useful output wasn't a screen. It was a specification and an API contract. That gave the coding agents bounded tasks and gave me something concrete to review.”

### Không nên kể

> “I tried an LLM-only app, it failed by 258 days, and then I invented the hybrid design.”

**Không đúng chronology mà history thể hiện.** Kiến trúc tách extraction và estimation đã có trong initial spec. Benchmark được thêm/đo sau đó để kiểm tra, không phải bằng chứng cho một câu chuyện khám phá trước đó.

---

## 2. Bạn dùng stub để không bị live API chặn cả quá trình build

### Bằng chứng

- D2 trong initial commit ghi chưa có API key và có deterministic stub.
- `73a13c4` bổ sung DeepSeek provider sau core services/API/frontend ban đầu.
- `fac6c56` bổ sung test bootstrap ép stub.

### Ý nghĩa để kể

Bạn tách dependency cần thiết lúc chạy sản phẩm khỏi dependency cần thiết cho mỗi vòng development. Khi live extraction chưa sẵn sàng, vẫn có thể làm DB, API, UI, replay và kiểm tra integration bằng output có cấu trúc.

### Câu nói

> “I didn't make every development step depend on a live model call. The stub let me work on the rest of the pipeline, then evaluate the real provider separately.”

### Giới hạn

Stub không đại diện chất lượng LLM thật. Test offline pass không chứng minh provider thật đáng tin. Cái hay là **tách hai câu hỏi ra để kiểm tra**, không phải giả vờ stub bằng LLM.

---

## 3. Bạn không dừng ở backend — history có cả integration và thao tác của người dùng

### Bằng chứng

- `0f42715` — Monte Carlo over unknown inputs.
- `0d198e3` — API nối answers, packages và MC.
- `9c8bcaa` — frontend cho người dùng trả lời và thấy kết quả thay đổi.
- `ee90a07`, `c648dc1` — UI, hướng dẫn và tour.
- `894ff5d` — override feature và xem thêm unknowns, giữ dấu vết extraction ban đầu.
- `1c98145` — CSV mẫu để thử import.
- `fa29570` — preload estimate trước khi tour đi vào màn estimate.

### Ý nghĩa để kể

AI không chỉ giúp viết algorithm. Nó giúp triển khai xuyên các lớp, nhưng mỗi lần thêm behavior phải nối service, API, types, state và screen. Những commit usability cho thấy sản phẩm được sửa ở chỗ người dùng thao tác, không chỉ chỗ model tính.

### Câu nói

> “A feature wasn't finished when the service returned the right object. It had to survive the API contract and become an action the user could understand.”

### Giới hạn

History có UI iteration, **không tự chứng minh formal user testing, adoption hay time savings**. Nếu có feedback thật, kể rõ ai đã thử và thấy gì; đừng tự bổ sung.

---

## 4. QA làm lộ những lỗi app happy-path không cho thấy

### Bằng chứng mạnh: `1718a8e`

Commit và diff ghi rõ:

- Hai request song song có thể chọn cùng project ID rồi lỗi unique constraint.
- Sửa bằng `BEGIN IMMEDIATE` bao ID allocation và persistence, có rollback.
- Regression test chạy 8 parallel persistence calls, kiểm tra ID riêng biệt và stored count.
- NaN/Infinity bị loại khỏi actual effort để không làm hỏng training/replay.
- CSV validation loại feature value không hợp lệ.
- Cache replay với `min_train` khác phải được invalidated khi dữ liệu đổi.

### Ý nghĩa để kể

Đây là ví dụ mạnh để trả lời “242 tests có ý nghĩa gì?”. Không cần đọc 242. Mở một test và giải thích **business consequence của failure**: mất kết quả, nhập dữ liệu sai, replay cũ sau khi actual đổi.

### Câu nói

> “The happy path worked, but review exposed failures around concurrent requests and invalid data. I needed regression cases for those boundaries, not just a successful estimate on a sample email.”

### Giới hạn

Một test race pass không biến SQLite app thành hệ thống đã load-test đầy đủ. Nói đúng **lỗi quan sát được và boundary được sửa**.

---

## 5. Deployment buộc bạn sửa giả định về môi trường

### Bằng chứng

- `e0a83d3` — Next.js static export được FastAPI serve cùng API; một Docker service, một origin.
- `8c9e15f` — image cần Git executable cho analyzer.
- `40f27eb` — có thêm `.git` copy trong image.
- `ab6519c` — hard copy `.git` làm cloud build fail vì Render build context không có thư mục đó; đổi sang conditional copy.
- `8f1cd42` — fallback clone cho self-analysis ở cloud.

### Ý nghĩa để kể

Bạn có một câu chuyện **local assumption → cloud failure → isolate optional dependency → restore optional behavior**. Nó thực tế hơn “tôi deploy lên Render và mọi thứ hoạt động”.

### Câu nói

> “Local success hid a deployment assumption: Git metadata existed in my checkout but not in Render's build context. I made that dependency optional so it couldn't block the whole app, then added a separate fallback for the optional analysis feature.”

### Giới hạn

Kể rõ initial fix và later fix. Đừng trình bày temporary degraded behavior là trạng thái cuối cùng của app.

---

## 6. Một bug rất hay để panel thấy cách bạn kiểm tra evidence

### Chuỗi thay đổi

- `2144113` mở rộng tìm coverage report trong subdirectories.
- `8f1cd42` thêm self-analysis fallback ở cloud.
- `d72eec7` sửa đọc nhầm coverage report của repo con/demo fixture.

### Failure

Analyzer tìm được XML hợp lệ nhưng của một demo repository bên trong checkout. Local có fixture đó, cloud không có, nên ra score khác nhau.

### Fix thực tế

Diff thêm điều kiện: ít nhất một class filename trong report phải resolve thành file trong analyzed checkout. Nếu không, coverage signal là unknown. Cùng commit thêm regression test.

### Cách kể

> “The input was syntactically valid but semantically belonged to the wrong object. I had to verify ownership of the evidence, not just whether the file could be parsed.”

### Vì sao hợp Anduin

Đây là cách nghĩ có thể chuyển sang document workflows: đúng format chưa đủ; phải đúng source, đúng entity, đúng version. **Chỉ là transferable lesson**, không phải claim app đã làm được financial entity/version validation.

---

## 7. Sau Fest Night, bạn sửa cả giả định, không chỉ code

### Thứ tự có thể chứng minh

1. `0f42715` — sampler marginal xuất hiện trong build ban đầu.
2. `3d89142` ngày 23/10 — experiment random masking.
3. `531d8de` ngày 24/10 — replay với LLM-extracted features và question-loop experiment.
4. `16718b5` — so sánh estimator baselines.
5. `f94f78d` — conditional prior, runtime integration, prior-building script, corrected report và D31.

### Bài học

Random missing không giống missing vì email không nhắc. Sample ở marginal 25.2% làm feature không được nhắc bị thêm quá nhiều. Trong extraction-null cells, positive chỉ khoảng 4.1%.

Result của cùng replay:

- Marginal prior: MAE 49.64.
- Zero-fill: MAE 21.34.
- Conditional prior: MAE 20.48, coverage 85.3%.

### Attribution và timing phải đúng

D31 ghi rõ external reviews đã challenge specification. Không cần sửa thành câu chuyện bạn tự phát hiện mọi thứ. Điểm mạnh là **tiếp nhận critique, làm experiment đúng, triển khai correction và ghi rõ giới hạn**.

Những commit này **sau Fest Night ngày 22/10**. Khi panel hỏi quá trình challenge ban đầu, tách rõ:

> “That was part of the later improvement work after Fest Night, not a result I had at the initial submission.”

### Câu nói

> “The more important failure wasn't code that crashed. It was code that correctly implemented an assumption I needed to change. Later review helped expose it, and I verified the correction rather than just defend the first design.”

---

## 8. Handoff và communication cũng là phần của build

### Bằng chứng

- `e1eb11d`, `e88c1ec`, `d5d2a85`, `4daf23e`, `64b96e6` — handoff được tạo và cập nhật nhiều lần.
- `847c1b2`, `339d19c`, `576ac35` — sửa số liệu stale và claims không có source.
- `cf04a3f`, `d2aabcd` — viết lại README cho dễ đọc.

### Ý nghĩa

Work không chỉ nằm trong chat. Có artifact giữ state, contracts, caveats và next actions. Đặc biệt với AI-assisted development, documentation cũng cần fact-check vì generated prose có thể lặp lại số cũ hay kể một anecdote không đúng.

### Câu nói

> “I treated documentation as part of the system's correctness. The history includes claim corrections and handoff updates, because another agent—or a teammate—needs the actual state, not the most flattering summary.”

### Không nên nói quá

History vẫn còn nhãn slide chưa rõ và transcript từng kể sai. Đừng nói đã audit thì mọi claim tuyệt đối đúng. Nói đây là thói quen cần duy trì và tiếp tục cải thiện.

---

## Bản kể tự nhiên bằng tiếng Việt — để hiểu rồi nói bằng lời của bạn

“Nếu tóm lại cách em build thì em không bắt đầu bằng việc nhờ AI làm nguyên một app. Em bắt đầu bằng cách định nghĩa workflow và giao diện giữa các phần. Request vào sẽ ra feature gì, unknown khác absent thế nào, estimator trả object gì, API đưa cho frontend ra sao. Spec và API contract đã có ở commit đầu.

Sau đó em dùng agent để triển khai các phần riêng, có file ownership và contract chung. Lợi ích là em có thể song song hóa, nhưng vẫn biết phải kiểm tra chỗ nào khi nối chúng lại. Em có stub để development không phụ thuộc mỗi lần vào live model.

Phần khó không chỉ là agent viết được code. Có những lỗi chỉ lộ khi integration hoặc deploy: concurrent requests trùng ID, dữ liệu NaN/Infinity, thiếu Git trong image, rồi cloud không có `.git` như local. Em phải biến các lỗi đó thành failure case cụ thể, sửa boundary và thêm regression test.

Một ví dụ em thích là local/cloud ra risk khác nhau. Cuối cùng nguyên nhân là đọc nhầm coverage report của một demo repository nằm trong checkout. XML đúng nhưng source sai. Fix không phải ép hai con số giống nhau; phải kiểm tra report có liên quan đến repo đang phân tích không, nếu không thì để unknown.

Sau Fest Night em còn kiểm tra sâu hơn phần missing data. Experiment đầu random-mask nhìn khá tốt, nhưng khi chạy với extraction thật thì sampler sai hơn cả zero-fill. External review giúp challenge giả định đó. Em đổi cách hiểu null, dùng prior phù hợp và so sánh lại cùng protocol.

Nên điều em học được là AI tăng tốc implementation, nhưng không thay trách nhiệm đặt đúng bài toán. Một đoạn code có thể chạy đúng theo yêu cầu mà chính yêu cầu đang sai. Em cần hiểu critical path, chấp nhận feedback, kiểm chứng correction và để lại artifact cho người tiếp theo.”

**Cách dùng:** Đây là retrospective synthesis từ artifact. Thay “em làm/phát hiện” bằng attribution thật khi cần. Không dùng nó để dựng một prompt history không có thật.

## Điều cần bạn tự bổ sung để câu chuyện thật sự là của bạn

1. Model coding cụ thể từng dùng trong OpenCode.
2. Một instruction thật, dù chỉ paraphrase, và output bạn đã review.
3. Một lần bạn không đồng ý với output và lý do.
4. Bạn trực tiếp kiểm tra phần nào, agent/reviewer đóng góp phần nào.
5. Timeline giờ thực làm và cách quản lý session nếu bạn nhớ.
6. Feedback người dùng thật, nếu có; không suy ra từ UI commits.

**Thông điệp kết:** “Em không chỉ biết nhờ AI tạo phần mềm. Em biết chia việc, kiểm tra, tìm nguyên nhân khi sai và chịu trách nhiệm với kết quả.”
