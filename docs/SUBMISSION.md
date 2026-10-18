# Submission package — The Estimator

## Short description (EN, ~180 words)

**The Estimator** turns messy customer emails into honest effort estimates.

Paste an RFP: an LLM (DeepSeek V4.1 Flash) extracts 15 engineering-complexity features with verbatim evidence, then *math* — Ridge regression + conformal prediction — produces a calibrated range (P10/P50/P90). Unknown inputs are never silently guessed: they are Monte-Carlo sampled so missing information widens the range, and the ranked clarifying questions turn the conversation around — answering them shrinks the range live. A budget-fit quote builder proposes Essential/Standard/Full packages with an over-budget probability. When a project finishes, entering actual days retrains the model; a mid-history productivity drift in the demo data proves the loop adapts while human estimates do not (last 10 projects: MAE 31.05 vs 52.90).

A walk-forward replay measures everything for real: system MAE 17.36 days over the full 218-step walk-forward (team 32.93); on the 42 most recent steps LLM + company history scores 35.27 vs 258.12 for LLM-only (it confuses calendar time with effort). Extraction quality is measured too (F1 0.933). An optional **codebase layer** measures repository friction and similar past changes to flag risk (mechanism validated on 29k real commits; honest negative on text-prediction). No chat gimmicks: a single-URL workflow dashboard. Runs fully offline with a deterministic stub; demo data is synthetic and disclosed.

## Mô tả ngắn (VI, ~190 từ)

**The Estimator** biến email yêu cầu khách hàng thành ước lượng effort trung thực.

Dán email/RFP: LLM (DeepSeek V4.1 Flash) trích xuất 15 đặc trưng phức tạp kèm trích dẫn gốc, sau đó **toán học** (hồi quy Ridge + conformal prediction) đưa ra khoảng tin cậy P10/P50/P90. Thông tin thiếu không bị đoán bừa: feature "không rõ" được lấy mẫu Monte Carlo để khoảng giãn ra trung thực, các câu hỏi làm rõ xếp theo mức ảnh hưởng — **trả lời từng câu, khoảng co lại ngay**. Công cụ báo giá gợi ý 3 gói Essential/Standard/Full kèm xác suất vượt ngân sách. Nhập số ngày thực tế → mô hình học lại; cú drift năng suất giữa chừng chứng minh vòng học thích nghi, còn ước lượng của đội thì không (10 dự án cuối: MAE 31.05 so với 52.90).

Replay đo thật walk-forward: hệ thống MAE 17.36 trên 218 bước (team 32.93); 42 bước cuối: LLM + lịch sử 35.27, LLM thuần 258.12 (lẫn thời gian lịch với effort). Extraction cũng được đo (F1 0.933). Lớp **codebase tùy chọn** đo ma sát repo + thay đổi tương tự quá khứ để cảnh báo rủi ro (validate trên 29k commit thật). Không giao diện chat — dashboard 1 URL. Chạy offline bằng stub; dữ liệu demo mô phỏng, ghi rõ trong app/README.

## Links (điền sau khi deploy)

- Live app: **https://the-estimator-xqzc.onrender.com** (verified live 2026-10-18: `/api/health` ok, deepseek, calibrated; Codebase Lab examples work — see `HANDOFF.md` §5)
- GitHub repo (public): https://github.com/iknizzz1807/the-estimator
- Video demo: optional

## Checklist nộp bài (checklist.md Phase 8)

- [x] Live App hoạt động từ public URL
- [x] GitHub repo public, clone được
- [x] README đầy đủ + sơ đồ Mermaid
- [x] Không có .env / API key / node_modules bị commit
- [x] Mô tả ngắn 100–200 từ (file này)
- [ ] Nộp qua portal trước 23:59 ngày 18/10/2026
