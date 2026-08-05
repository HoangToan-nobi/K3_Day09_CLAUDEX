# Báo cáo cá nhân — Hoàng Sỹ Toàn

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
|---|---|
| Họ và tên | Hoàng Sỹ Toàn |
| MSSV | 2A202601273 |
| Khóa/Lớp | K3 / D304 |
| Vai trò chính | Coordinator và Policy/Integration Engineer |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

| Module/deliverable | File/hàm phụ trách | Input | Output | Trạng thái |
|---|---|---|---|---|
| Điều phối pipeline | `app/agents/coordinator.py` / `CoordinatorAgent.process_case` | Case JSON và kết quả handoff | Output case đã verify | Hoàn thành |
| Policy engine | `app/agents/policy_agent.py` / `evaluate_policy` | Order, payment, delivery results | Primary issue, cause, refund, action | Hoàn thành |
| Tích hợp và output | `app/main.py`, `app/utils/output_builder.py` | Kết quả các agent | 50 JSON và trace | Hoàn thành |

## 3. Kết quả theo vai trò

- Xây dựng luồng Coordinator → Order/Seller → Payment → Delivery → Policy → Verifier.
- Triển khai thứ tự ưu tiên của 6 business rule trong `EC_POLICY_V1`.
- Tạo output cho 50 case và kiểm tra thành công 50/50 case.
- Kết quả kiểm thử: 81 tests passed.

Lệnh xác minh:

```bash
.venv/bin/python -m app.main
.venv/bin/python scripts/validate_outputs.py
.venv/bin/python -m pytest -q
```

## 4. Giải thích phần kỹ thuật

### Vấn đề cần giải quyết

Một khiếu nại phải được đối chiếu từ nhiều domain dữ liệu và chỉ được hoàn tiền khi business rule có bằng chứng tương ứng.

### Cách triển khai

Coordinator nhận `claimed_order_id`, gọi từng agent theo đúng trách nhiệm, sau đó chuyển kết quả typed dataclass sang Policy Agent. Policy Agent dùng rule chain thuần, trong đó rule đầu tiên khớp sẽ quyết định primary issue. Output Builder định dạng JSON, còn Verifier kiểm tra lại trước khi ghi file.

Các rule được áp dụng theo thứ tự: canceled paid, unavailable paid, seller delivery late, logistics delivery late, valid split payment và unsupported late claim.

### Input, output và contract

| Thành phần | Mô tả |
|---|---|
| Input | `input/EC_*.json`, đặc biệt `customer_request.claimed_order_id` |
| Output | JSON theo schema README trong `output/` |
| Module phụ thuộc | Order/Seller, Payment, Delivery Agent |
| Module sử dụng output | Output Builder và Verifier |
| Điều kiện lỗi | Case thiếu order, thiếu trường bắt buộc hoặc không match rule |

### Cách xác minh

```bash
.venv/bin/python scripts/validate_outputs.py
```

- Kết quả mong đợi: 50 output hợp lệ.
- Kết quả thực tế: 50/50 verified, không thiếu file, không có file thừa.
- Artifact: `logging/trace.jsonl`, `logging/metadata.json`, `output.zip`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Có nên dùng LLM để quyết định refund và root cause hay không.
- **Phương án:** Gọi model cho từng case hoặc dùng deterministic Python rules.
- **Lựa chọn:** Deterministic Python rules.
- **Lý do:** Các rule, timestamp, tổng tiền và evidence đều được định nghĩa rõ; code thuần cho kết quả tái lập, không bịa evidence và không phụ thuộc API.
- **Bằng chứng:** Toàn bộ 50 case được xử lý ổn định và 81 unit/integration tests đều passed.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng:** Output ban đầu có evidence quá rộng, khiến điểm phần Bằng chứng thấp.
- **Nguyên nhân:** Evidence được sinh chung cho mọi issue, bao gồm seller evidence không liên quan.
- **Cách xử lý:** Tạo `EVIDENCE_SCOPE_BY_ISSUE` để chọn evidence theo từng primary issue; riêng canceled paid giữ thêm item/seller evidence sau khi kiểm thử leaderboard.
- **Xác minh:** Chạy lại pipeline, validator và so sánh 50 output với output tái sinh.
- **Bài học:** Evidence cần vừa hợp lệ vừa liên quan trực tiếp đến kết luận; thêm ID thừa có thể bị grader phạt.

## 7. Hiểu biết về luồng end-to-end

1. Input case cung cấp order ID. Coordinator dùng ID đó để gọi các agent phân tích order/item/seller, payment và delivery.
2. Các agent handoff kết quả typed qua Coordinator. Policy Agent áp dụng rule, Output Builder tạo schema, Verifier kiểm tra rồi ghi JSON.
3. Trace ghi lại từng handoff; metadata ghi framework, model và runtime.
4. Vì output được chấm độc lập theo từng case, cùng một pipeline phải xử lý đủ 50 case và giữ schema ổn định.
5. Thành công được xác minh bằng 50 file JSON hợp lệ, evidence tồn tại trong CSV, số tiền đúng và test suite passed.

## 8. Cam kết

- [x] Nội dung phản ánh phần điều phối và policy đã thực hiện.
- [x] Có thể giải thích luồng end-to-end.
- [x] Không ghi nhận kết quả chưa được kiểm chứng.
- [x] Không chứa secret.
- [x] Không sao chép nguyên văn báo cáo thành viên khác.

**Họ và tên:** Hoàng Sỹ Toàn  
**Ngày xác nhận:** 2026-08-05
