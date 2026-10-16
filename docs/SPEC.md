SPEC — THE ESTIMATOR

Phiên bản: 2.0
Ngày tạo: 16/10/2026
Mục đích: Mô tả bài toán, luồng nghiệp vụ, logic và lý do thiết kế. Không bao gồm implementation details.

---

1. BỐI CẢNH NGHIỆP VỤ

1.1. Vấn đề trong một câu

Các công ty dịch vụ phần mềm ước lượng effort cho dự án mới dựa trên cảm tính của Tech Lead, không học từ quá khứ, không phát hiện thông tin thiếu, và không đo lường được độ chính xác của chính mình.

1.2. Chi phí của vấn đề

Hệ quả Chi phí ước tính
Ước lượng sai → làm lỗ hợp đồng 15–30% margin dự án
Không phát hiện thông tin thiếu → scope creep 20–40% effort phát sinh
Không học từ quá khứ → lặp lại sai lầm Không đo được, nhưng tích lũy
Ước lượng mất 1–3 giờ/lần → chậm response khách Mất cơ hội cạnh tranh

1.3. Ai có vấn đề này

· Công ty outsource/consulting (10–500 người): Sales gửi RFP, Tech Lead ước lượng thủ công.
· Product team trong công ty lớn: PM cần estimate sprint/epic.
· Agency: Nhận brief từ client, cần báo giá nhanh.

1.4. Tại sao bây giờ

· LLM đủ tốt để đọc hiểu RFP và trích xuất thông tin có cấu trúc.
· Dữ liệu lịch sử dự án đã được số hóa (Jira/Harvest/Excel).
· Kỹ thuật thống kê (Conformal Prediction) cho phép đưa ra khoảng có cơ sở, không chỉ một con số.

---

2. NGƯỜI DÙNG VÀ NHU CẦU

2.1. Persona chính: Sales/BD

Đặc điểm Mô tả
Công việc hàng ngày Nhận email khách, đánh giá cơ hội, gửi proposal
Nỗi đau Không biết ước lượng, phải chờ Tech Lead 1–2 ngày
Điều họ muốn Trả lời khách trong ngày, có cơ sở để đàm phán
Cách đo thành công Thời gian từ khi nhận email đến khi gửi proposal

2.2. Persona phụ: Tech Lead/PM

Đặc điểm Mô tả
Công việc hàng ngày Review requirement, chia task, theo dõi tiến độ
Nỗi đau Bị interrupt để estimate, không có thời gian đọc kỹ RFP
Điều họ muốn Công cụ gợi ý để review nhanh, không phải làm từ đầu
Cách đo thành công Thời gian review estimate giảm

2.3. Persona phụ: Quản lý/Chủ công ty

Đặc điểm Mô tả
Công việc hàng ngày Quản lý margin, quyết định giá
Nỗi đau Không biết ước lượng của team có chính xác không
Điều họ muốn Nhìn thấy accuracy trend theo thời gian
Cách đo thành công Margin dự án tăng, ít dự án lỗ

---

3. LUỒNG NGHIỆP VỤ

3.1. Luồng 1: Setup ban đầu (1 lần)

```
[Người dùng mở app lần đầu]
         ↓
[Hệ thống hỏi: Bạn có dữ liệu lịch sử không?]
         ↓
    ┌────┴────┬─────────┬──────────┐
    ↓         ↓         ↓          ↓
[Import]  [Upload]  [Nhập tay]  [Bắt đầu
 Jira      CSV       10 dự án    không có]
(soon)                          (Cold Start)
    ↓         ↓         ↓          ↓
    └────┬────┴─────────┴──────────┘
         ↓
[Hệ thống calibrated]
         ↓
[Dashboard hiện: "Độ chính xác dự kiến: X%"]
```

Quyết định thiết kế: Cho phép Cold Start vì hệ thống vẫn có giá trị ngay cả khi chưa có dữ liệu — đó là khả năng phát hiện thông tin thiếu trong RFP.

3.2. Luồng 2: Estimate một dự án mới (hàng ngày)

```
[Sales paste email khách vào ô input]
         ↓
[Hệ thống trích xuất 15 features]
         ↓
[Hệ thống kiểm tra evidence cho từng feature]
         ↓
[Hệ thống so sánh với checklist yêu cầu]
         ↓
[Phát hiện: 4 thông tin còn thiếu]
         ↓
[Hệ thống tính estimate cho từng giả định]
         ↓
[Xếp hạng câu hỏi theo mức ảnh hưởng]
         ↓
[Hiển thị kết quả cho Sales]
         ↓
[Sales copy câu hỏi → paste vào email trả khách]
         ↓
[Sales export proposal PDF]
```

Quyết định thiết kế: Kết quả trả về là khoảng (P10/P50/P90), không phải một con số. Lý do: khoảng trung thực hơn về độ không chắc chắn, và giúp Sales đàm phán linh hoạt.

3.3. Luồng 3: Ghi nhận thực tế (sau khi dự án xong)

```
[Dự án chuyển sang trạng thái Done]
         ↓
[Hệ thống gửi nhắc nhở: "Nhập số ngày thực tế?"]
         ↓
[PM/Tech Lead nhập actual_days]
         ↓
[Hệ thống hiển thị: "Dự án này vượt 37%"]
         ↓
[Hệ thống cập nhật hệ số hiệu chỉnh]
         ↓
[Hiển thị: "Hệ số 'third_party' tăng từ 1.35 lên 1.41"]
         ↓
[Hiển thị: "Độ chính xác của bạn: 62% (tăng từ 45%)"]
```

Quyết định thiết kế: Hiển thị tác động của việc nhập liệu lên hệ số để PM thấy được lợi ích cá nhân — đây là gamification tự nhiên, không phải bị ép.

3.4. Luồng 4: Review accuracy (hàng tháng)

```
[Quản lý mở dashboard Accuracy]
         ↓
[Xem biểu đồ: Sai số theo thời gian]
         ↓
[Xem 3 đường: Team estimate vs LLM-only vs System]
         ↓
[Xem coverage: % thực tế nằm trong khoảng dự đoán]
         ↓
[Quyết định: Có cần điều chỉnh process không?]
```

3.5. Luồng 5: Replay History (demo mode)

```
[Người dùng bấm "Replay History"]
         ↓
[Hệ thống chạy animation: dự án 1 → 50]
         ↓
[Với mỗi dự án i: train trên i-1 dự án trước]
         ↓
[So sánh dự đoán vs thực tế]
         ↓
[Vẽ biểu đồ sai số giảm dần]
         ↓
[So sánh với baseline (team estimate, LLM-only)]
```

Quyết định thiết kế: Đây là màn chứng minh quan trọng nhất. Nó chứng minh hệ thống "học" thật, không phải chỉ là một LLM wrapper.

---

4. LOGIC NGHIỆP VỤ

4.1. Logic trích xuất thông tin

Input: Email/RFP dạng text.

Output:

· Danh sách features có/không/không rõ.
· Câu trích dẫn gốc cho mỗi feature (evidence).
· Danh sách thông tin còn thiếu.

Quy tắc:

1. Nếu feature được đề cập rõ ràng trong email → đánh dấu có/không.
2. Nếu feature chỉ được gợi ý → đánh dấu "không rõ" với confidence thấp.
3. Nếu feature không được đề cập → đánh dấu "thiếu thông tin".
4. Mỗi feature phải có câu trích dẫn gốc. Nếu không tìm thấy → flag để review.

4.2. Logic ước lượng

Input: Feature vector (15 chiều).

Output: Khoảng [P10, P50, P90].

Nguyên tắc:

1. Ước lượng dựa trên dữ liệu lịch sử, không dựa trên LLM.
2. Mỗi feature có một hệ số ảnh hưởng (ví dụ: third_party ×1.35).
3. Hệ số được học từ dữ liệu, không hardcode.
4. Khoảng [P10, P90] có coverage guarantee — nếu nói 80% thì thực tế ~80%.
5. Khi chưa có dữ liệu → dùng industry baseline với khoảng rộng hơn.

4.3. Logic phát hiện thông tin thiếu

Input: Features đã trích xuất + Checklist yêu cầu.

Output: Danh sách câu hỏi xếp hạng theo mức ảnh hưởng.

Nguyên tắc:

1. Với mỗi feature chưa biết, tính estimate cho cả hai trường hợp (có/không).
2. Chênh lệch giữa hai estimate là mức ảnh hưởng.
3. Câu hỏi có ảnh hưởng lớn nhất được xếp lên đầu.
4. Câu hỏi phải cụ thể và trả lời được, không chung chung.
5. Mỗi câu hỏi đi kèm với ước tính mức ảnh hưởng (ví dụ: "+20 ngày").

4.4. Logic học hỏi

Input: Số ngày thực tế của một dự án vừa xong.

Output: Hệ số hiệu chỉnh được cập nhật.

Nguyên tắc:

1. Mỗi dự án mới là một training sample.
2. Hệ số được cập nhật ngay lập tức (không cần chờ batch).
3. Hệ số cập nhật theo trung bình trượt để tránh bị ảnh hưởng quá mức bởi một dự án.
4. Có thể xem lịch sử thay đổi hệ số để audit.
5. Độ chính xác được đo lường liên tục và hiển thị cho người dùng.

4.5. Logic so sánh với LLM-only

Mục đích: Chứng minh hệ thống không chỉ là "LLM wrapper".

Nguyên tắc:

1. Chạy cùng một email qua LLM-only 10 lần.
2. Ghi nhận tất cả kết quả.
3. So sánh độ dao động (std) và độ chính xác (MAE).
4. Hiển thị kết quả song song trên UI.

---

5. BỘ FEATURES (MỞ RỘNG)

5.1. Lý do mở rộng

Với chỉ 5 features:

· Chỉ có 2^5 = 32 tổ hợp feature patterns → quá ít để phân biệt các dự án.
· Không thể hiện được chiều sâu hiểu biết về domain phần mềm.
· Model không học được sự tương tác giữa các yếu tố.

Với 15 features:

· Có 2^15 = 32,768 tổ hợp → đủ để phân biệt các dự án.
· Thể hiện hiểu biết về các chiều phức tạp khác nhau của phần mềm.
· Cho phép phân tích chi tiết hơn về yếu tố nào ảnh hưởng nhiều nhất.

5.2. Phân nhóm features

15 features được chia thành 5 nhóm theo loại phức tạp:

Nhóm A: Độ phức tạp tích hợp (4 features)

# Feature Định nghĩa Tại sao quan trọng
1 third_party_api Tích hợp API/dịch vụ bên ngoài Integration thường chiếm 30–50% effort, dễ phát sinh lỗi
2 payment_gateway Tích hợp cổng thanh toán Yêu cầu bảo mật cao, testing phức tạp, compliance
3 identity_provider Tích hợp SSO/OAuth/IdP Đụng đến security, cần test nhiều edge cases
4 external_data_sync Đồng bộ dữ liệu với hệ thống ngoài Race conditions, retry logic, conflict resolution

Nhóm B: Độ phức tạp dữ liệu (3 features)

# Feature Định nghĩa Tại sao quan trọng
5 data_migration Di chuyển dữ liệu từ hệ thống cũ Rủi ro mất dữ liệu, cần validation, downtime
6 multi_currency Hỗ trợ nhiều loại tiền tệ Xử lý tỷ giá, làm tròn, lịch sử tỷ giá
7 multi_tenancy Kiến trúc multi-tenant Ảnh hưởng toàn bộ database schema, security

Nhóm C: Độ phức tạp giao diện (3 features)

# Feature Định nghĩa Tại sao quan trọng
8 realtime_ui Giao diện cập nhật real-time (<100ms) Cần WebSocket/SSE, state management phức tạp
9 mobile_app Ứng dụng mobile native (không phải responsive) Cần iOS + Android, app store process
10 offline_mode Hoạt động khi mất kết nối Cần local storage, sync logic, conflict resolution

Nhóm D: Bảo mật và tuân thủ (3 features)

# Feature Định nghĩa Tại sao quan trọng
11 pci_dss Tuân thủ PCI-DSS (thanh toán) Audit, encryption, logging, testing nghiêm ngặt
12 privacy_compliance Tuân thủ GDPR/HIPAA Data handling, consent, right to deletion
13 audit_logging Yêu cầu audit trail chi tiết Logging infrastructure, retention, query

Nhóm E: Ngữ cảnh dự án (2 features)

# Feature Định nghĩa Tại sao quan trọng
14 legacy_tech_stack Làm việc với công nghệ cũ Ít tài liệu, khó test, khó tìm dev
15 cross_team_coordination Cần phối hợp nhiều team Communication overhead, dependency management

5.3. Features KHÔNG được chọn (và lý do)

Feature Lý do loại
issue_type (bug/feature) Đây là categorical, không phải binary. Có thể thêm sau như một feature riêng.
priority Không ảnh hưởng đến effort, chỉ ảnh hưởng đến thứ tự làm.
team_size Là input của estimation, không phải feature của dự án.
description_length Là proxy yếu, dễ gây nhiễu.
num_stakeholders Khó trích xuất từ email, thường không được đề cập.

5.4. Tương tác giữa các features

Một số features có tương quan với nhau:

· payment_gateway thường đi kèm pci_dss (nếu là thanh toán thẻ).
· multi_tenancy thường đi kèm audit_logging (yêu cầu enterprise).
· mobile_app thường đi kèm offline_mode (yêu cầu từ người dùng mobile).
· external_data_sync thường đi kèm realtime_ui (yêu cầu đồng bộ).

Quyết định thiết kế: Không tự động suy diễn tương quan. Để model học từ dữ liệu. Nếu có đủ dữ liệu, model sẽ tự phát hiện interaction effects.

5.5. Chiến lược triển khai features

Giai đoạn Features Lý do
Demo chính 15 features Đủ để thể hiện chiều sâu
Nếu thiếu thời gian 8 features (nhóm A + B) Vẫn đủ để demo cơ chế
Nếu dùng TAWOS 10 features (bỏ 5 features khó extract) TAWOS không có thông tin về compliance

---

6. LÝ DO THIẾT KẾ

6.1. Tại sao trả về khoảng, không phải một con số?

Vấn đề với một con số:

· Tạo anchoring bias — người ta bám vào con số đó và không điều chỉnh.
· Che giấu độ không chắc chắn — người dùng không biết khi nào nên tin.
· Không thể đàm phán — khách hàng không có cơ sở để thương lượng.

Lợi ích của khoảng:

· Thể hiện trung thực về độ không chắc chắn.
· Cho phép đàm phán linh hoạt — "khoảng 25–52 ngày, tùy thuộc vào một số yếu tố".
· Có thể đo lường độ chính xác — coverage của khoảng có thể kiểm chứng được.

6.2. Tại sao tách LLM extraction khỏi toán học?

Nếu để LLM làm tất cả:

· Kết quả dao động — 10 lần chạy ra 10 số khác nhau.
· Không calibrate được — không biết khi nào LLM đúng, khi nào sai.
· Không học được từ dữ liệu công ty.

Nếu tách ra:

· LLM chỉ làm việc trích xuất — nó giỏi việc này.
· Toán học làm việc ước lượng — nó đảm bảo tính nhất quán.
· Có thể thay thế LLM bằng classifier nhỏ hơn khi có đủ dữ liệu.
· Có thể audit — biết chính xác tại sao ra con số đó.

6.3. Tại sao Cold Start vẫn có giá trị?

Ngay cả khi chưa có dữ liệu lịch sử, hệ thống vẫn:

· Phát hiện thông tin thiếu — giúp Sales biết cần hỏi khách gì.
· Chuẩn hóa RFP — biến email lộn xộn thành cấu trúc.
· Đưa ra câu hỏi — giúp Sales chuyên nghiệp hơn trong mắt khách.

Đây là giá trị tức thì không cần chờ dữ liệu.

6.4. Tại sao không chỉ dùng LLM?

Tiêu chí LLM-only Hệ thống
Nhất quán Không (dao động ±15 ngày) Có (cùng input → cùng output)
Học từ dữ liệu Không Có
Khoảng tin cậy Không Có (coverage guarantee)
Audit được Không Có
Chi phí Cao ($0.01–0.1/request) Thấp sau khi train
Giải thích Khó Dễ (hệ số rõ ràng)

6.5. Tại sao dùng tập features đóng?

· Đảm bảo tính nhất quán — cùng một định nghĩa cho mọi dự án.
· Cho phép so sánh — có thể so sánh các dự án với nhau.
· Hỗ trợ học tập — có thể học từ dữ liệu lịch sử.
· Đo lường được — biết feature nào ảnh hưởng nhiều nhất.

Nếu dùng features mở (LLM tự do trích xuất), không thể đảm bảo các tính chất trên.

6.6. Tại sao hiển thị 3 dự án tương tự?

· Tăng độ tin cậy — người dùng thấy được cơ sở của estimate.
· Cho phép kiểm chứng — có thể so sánh với dự án đã biết.
· Hỗ trợ học tập — người dùng học được từ quá khứ.
· Tạo câu chuyện — dễ giải thích cho khách hàng hơn.

---

7. CHỈ SỐ THÀNH CÔNG

7.1. Chỉ số nghiệp vụ

Chỉ số Mục tiêu Cách đo
Thời gian estimate Giảm từ 1–3 giờ xuống < 5 phút Đo thời gian thực tế
Độ chính xác MAE < 10 ngày So sánh estimate vs actual
Coverage khoảng 80% 75–85% % actual nằm trong [P10, P90]
Tỷ lệ phát hiện thông tin thiếu 80% % thông tin thiếu được phát hiện
Tỷ lệ nhập actual 70% dự án % dự án được cập nhật actual

7.2. Chỉ số kỹ thuật (high-level)

Chỉ số Mục tiêu
Tính nhất quán Cùng input → cùng output (std < 5%)
Tốc độ < 5 giây cho toàn bộ pipeline
Chi phí < $0.01/estimate
Khả năng mở rộng Xử lý được 1000 dự án

---

8. PHẠM VI VÀ RÀNG BUỘC

8.1. Trong phạm vi

· Nhận email/RFP dạng text.
· Trích xuất 15 features.
· Ước lượng effort với khoảng tin cậy.
· Phát hiện thông tin thiếu và xếp hạng câu hỏi.
· Học từ dữ liệu thực tế.
· Giao diện dashboard hướng tác vụ.
· Màn chứng minh (Replay + A/B).

8.2. Ngoài phạm vi

· Tích hợp Jira/GitHub API (chỉ import CSV).
· Multi-user authentication.
· Real-time collaboration.
· Mobile app.
· Fine-tune LLM.
· Tự động gửi email cho khách.

8.3. Giả định

· Email/RFP bằng tiếng Anh hoặc tiếng Việt.
· Dữ liệu lịch sử có ít nhất 10 dự án để bắt đầu học.
· Người dùng có kiến thức cơ bản về phần mềm.
· Không có yêu cầu về regulatory compliance trong demo.

8.4. Ràng buộc

· Thời gian: 68 giờ.
· Nhân lực: 1 người.
· Ngân sách: $0–50 cho LLM API.
· Hạ tầng: Free tier.

---

9. EDGE CASES

Tình huống Hành vi mong muốn
Email rỗng Hiển thị lỗi: "Vui lòng paste email"
Email rất dài (> 10,000 chars) Cảnh báo: "Email dài, kết quả có thể kém chính xác"
Email không phải tiếng Anh/Việt Cố gắng trích xuất, flag nếu confidence thấp
Không có feature nào được phát hiện Hiển thị: "Không tìm thấy features, vui lòng review"
Feature mâu thuẫn Ví dụ: realtime_ui=1 nhưng offline_mode=1 → flag để review
Không có dữ liệu lịch sử Cold start mode, hiển thị khoảng rộng hơn
Dữ liệu lịch sử < 10 dự án Warm-up mode, hiển thị "Đang học"
Actual_days = 0 Không cho phép, hiển thị lỗi
Actual_days > 1000 Cảnh báo: "Giá trị bất thường, vui lòng kiểm tra lại"
Retrain model thất bại Giữ model cũ, hiển thị thông báo lỗi

---

10. NGUYÊN TẮC THIẾT KẾ UI

1. Không có giao diện chat. Tất cả là workflow UI — form, table, chart, card.
2. Mỗi màn hình có một mục đích rõ ràng. Không nhồi nhét nhiều chức năng.
3. Load Sample Data 1-click. Giám khảo không cần nhập liệu để thấy kết quả.
4. Loading states rõ ràng. Dùng SSE để stream từng bước, không show spinner vô định.
5. Error states có hướng dẫn. Không show stack trace, show "Vui lòng thử lại" + nút retry.
6. Dark mode mặc định. Tone Cyberpunk/Palantir — phù hợp với khán giả FinTech.
7. Số liệu có ngữ cảnh. Mỗi con số đi kèm với ý nghĩa (ví dụ: "P50 = 38 ngày, dựa trên 12 dự án tương tự").
8. Không dùng màu đỏ cho lỗi không nghiêm trọng. Dùng cam cho warning, đỏ chỉ cho critical.

---

11. GIỚI HẠN VÀ ĐIỀU CẦN GHI RÕ

11.1. Giới hạn phải ghi trong README

1. Dữ liệu demo là mô phỏng. Kết quả đẹp một phần do công thức ẩn. Production cần dữ liệu thật.
2. Story point ≠ person-day. Khi validate trên TAWOS, đơn vị là story point.
3. Feature extraction có thể sai. Đã có guardrails nhưng không hoàn hảo.
4. Conformal Prediction giả định exchangeability. Distribution shift có thể làm giảm coverage.
5. Chưa tích hợp Jira/GitHub API. Demo chỉ import CSV.
6. Không có multi-user. Không authentication, không phân quyền.

11.2. Điều KHÔNG được tuyên bố

· Không nói "chính xác 100%".
· Không nói "thay thế con người".
· Không nói "hoạt động trên mọi loại dự án".
· Không nói "không cần dữ liệu lịch sử".

---
