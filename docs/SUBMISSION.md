# Submission package — The Estimator

## Short description (EN, ~160 words)

**The Estimator** turns messy customer emails into honest effort estimates.

Paste an RFP: an LLM extracts 15 engineering-complexity features with verbatim evidence quotes, then *math* — Ridge regression + conformal prediction — produces a calibrated range (P10/P50/P90) instead of a single misleading number. Unknown inputs are detected automatically and ranked into ready-to-send clarifying questions by expected impact in days. When a project finishes, entering actual days retrains the model and updates per-feature coefficients with a visible audit trail.

A walk-forward replay re-predicts the company's entire project history (train on the past, predict the next) to prove the system actually learns — it beats both team estimates and LLM-only baselines on MAE. An A/B screen exposes LLM-only run-to-run variance side by side.

No chat gimmicks: a workflow dashboard for sales and tech leads. Runs fully offline with a deterministic stub extractor; add a DeepSeek (or Gemini) key for real LLM extraction. Demo data is synthetic and disclosed in the UI and README.

## Mô tả ngắn (VI, ~170 từ)

**The Estimator** biến email yêu cầu khách hàng thành ước lượng effort trung thực.

Dán email/RFP: LLM trích xuất 15 đặc trưng độ phức tạp kèm trích dẫn làm bằng chứng, sau đó **toán học** (hồi quy Ridge + conformal prediction) đưa ra khoảng tin cậy P10/P50/P90 thay vì một con số dễ gây ngộ nhận. Thông tin còn thiếu được phát hiện tự động và xếp hạng thành các câu hỏi làm rõ kèm mức ảnh hưởng (ngày). Khi dự án kết thúc, nhập số ngày thực tế sẽ huấn luyện lại mô hình, cập nhật hệ số từng đặc trưng kèm lịch sử audit.

Màn Replay chạy walk-forward trên toàn bộ lịch sử dự án (học quá khứ, dự đoán tương lai) để chứng minh hệ thống **học thật** — MAE tốt hơn cả ước lượng của đội và baseline LLM thuần. Màn A/B phơi bày độ dao động của LLM-only.

Không có giao diện chat — dashboard quy trình cho sales và tech lead. Chạy hoàn toàn offline bằng stub extractor; gắn DeepSeek (hoặc Gemini) key để dùng LLM thật. Dữ liệu demo là dữ liệu mô phỏng, được ghi rõ trong app và README.

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
