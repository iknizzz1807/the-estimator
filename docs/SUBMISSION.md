# Submission package — The Estimator

## Short description (EN, ~180 words)

**The Estimator** turns messy customer emails into honest effort estimates.

Paste an RFP: an LLM (DeepSeek V4.1 Flash) extracts 15 engineering-complexity features with verbatim evidence, then *math* — Ridge regression + conformal prediction — produces a calibrated range (P10/P50/P90). Unknown inputs are never silently guessed: they are Monte-Carlo sampled so missing information widens the range, and the ranked clarifying questions turn the conversation around — answering them shrinks the range live. A budget-fit quote builder proposes Essential/Standard/Full packages with an over-budget probability. When a project finishes, entering actual days retrains the model; a mid-history productivity drift in the demo data proves the loop adapts while human estimates do not (last 10 projects: MAE 15.7 vs 33.3).

A walk-forward replay measures everything for real: system MAE 23.5 days vs 30.4 (team) vs 36.0 (LLM + company history) vs 243 (LLM-only — it confuses calendar time with effort). Extraction quality is measured too (F1 0.92). No chat gimmicks: a single-URL workflow dashboard. Runs fully offline with a deterministic stub; demo data is synthetic and disclosed.

## Mô tả ngắn (VI, ~190 từ)

**The Estimator** biến email yêu cầu khách hàng thành ước lượng effort trung thực.

Dán email/RFP: LLM (DeepSeek V4.1 Flash) trích xuất 15 đặc trưng độ phức tạp kèm trích dẫn làm bằng chứng, sau đó **toán học** (hồi quy Ridge + conformal prediction) đưa ra khoảng tin cậy P10/P50/P90. Thông tin còn thiếu không bị đoán bừa: feature "không rõ" được lấy mẫu Monte Carlo để khoảng giãn ra trung thực, và các câu hỏi làm rõ được xếp hạng theo mức ảnh hưởng — **trả lời từng câu, khoảng co lại ngay trên màn hình**. Công cụ báo giá theo ngân sách gợi ý 3 gói Essential/Standard/Full kèm xác suất vượt ngân sách. Nhập số ngày thực tế → mô hình học lại; dữ liệu demo có cú drift năng suất giữa chừng chứng minh vòng học thích nghi, còn ước lượng của đội thì không (10 dự án cuối: MAE 15.7 so với 33.3).

Màn Replay đo thật walk-forward: hệ thống MAE 23.5 ngày, team 30.4, LLM + lịch sử 36.0, còn LLM thuần 243 (lẫn thời gian lịch với effort). Chất lượng extraction cũng được đo (F1 0.92). Không có giao diện chat — dashboard 1 URL duy nhất. Chạy offline hoàn toàn bằng stub; dữ liệu demo là mô phỏng, ghi rõ trong app và README.

## Links (điền sau khi deploy)

- Live app: TBD
- GitHub repo (public): TBD
- Video demo: optional

## Checklist nộp bài (checklist.md Phase 8)

- [ ] Live App hoạt động từ public URL
- [ ] GitHub repo public, clone được
- [ ] README đầy đủ + sơ đồ Mermaid
- [ ] Không có .env / API key / node_modules bị commit
- [ ] Mô tả ngắn 100–200 từ (file này)
- [ ] Nộp qua portal trước 23:59 ngày 18/10/2026
