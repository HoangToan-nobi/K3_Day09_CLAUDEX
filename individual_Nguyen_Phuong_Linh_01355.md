# Báo cáo cá nhân — Nguyễn Phương Linh

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
|---|---|
| Họ và tên | Nguyễn Phương Linh |
| MSSV | 2A202601355 |
| Khóa/Lớp | K3 / D304 |
| Vai trò chính | Delivery, Verification và Testing Engineer |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

| Module/deliverable | File/hàm phụ trách | Input | Output | Trạng thái |
|---|---|---|---|---|
| Delivery Agent | `app/agents/delivery_agent.py` | Order timestamps và item shipping limits | Delivery lateness, late sellers | Hoàn thành |
| Verifier Agent | `app/agents/verifier_agent.py` | Output và agent results | Verification errors hoặc verified output | Hoàn thành |
| Regression tests | `tests/test_policy_rules.py`, `tests/test_verifier.py` | Fixtures và output contracts | Test report | Hoàn thành |

## 3. Kết quả theo vai trò

- Triển khai so sánh `delivered_customer_date` với `estimated_delivery_date`.
- Triển khai kiểm tra handoff của seller theo `shipping_limit_date` từng item.
- Kiểm tra format và tồn tại của order/item/payment/seller/policy evidence.
- Kiểm tra refund, action, status, confidence và giới hạn số lượng ID.
- Kết quả cuối: 81 tests passed và 50/50 output verified.

## 4. Giải thích phần kỹ thuật

### Vấn đề cần giải quyết

Delivery claim phải phân biệt seller bàn giao trễ với logistics giao trễ. Ngoài ra, output hợp lệ về JSON chưa đủ; từng evidence và số tiền phải tồn tại và khớp dữ liệu gốc.

### Cách triển khai

Delivery Agent sử dụng kết quả ba trạng thái: `True`, `False` hoặc `None`. Chỉ kết luận giao trễ khi cả hai timestamp tồn tại và ngày giao thực tế lớn hơn ngày dự kiến. Seller được coi là bàn giao trễ khi carrier date lớn hơn shipping limit date của item thuộc seller đó.

Verifier Agent kiểm tra schema, case ID, entity existence, evidence format, financial values, refund basis, action/status consistency và confidence range. Các test fixtures mô phỏng nhiều item, nhiều payment, boundary tolerance và malformed evidence.

### Input, output và contract

| Thành phần | Mô tả |
|---|---|
| Input | `OrderRecord`, `ItemRecord`, output JSON và agent results |
| Output | `DeliveryResult`, verified output hoặc `VerificationError` |
| Module phụ thuộc | `app/schemas.py`, `app/data_loader.py`, config limits |
| Module sử dụng output | Policy Agent, Coordinator và output writer |
| Điều kiện lỗi | Null timestamp, ngày bằng nhau, evidence sai format, refund/action sai |

### Cách xác minh

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/validate_outputs.py
```

- Kết quả mong đợi: tất cả tests passed và 50 JSON hợp lệ.
- Kết quả thực tế: 81 passed; validator báo `ALL OUTPUTS VALID`.
- Artifact: `tests/fixtures/mini_olist/`, `logging/trace.jsonl`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Xử lý timestamp thiếu.
- **Phương án:** Coi timestamp thiếu là giao đúng hạn hoặc dùng trạng thái chưa xác định.
- **Lựa chọn:** Dùng `None`/undetermined.
- **Lý do:** Không được tự suy diễn một sự kiện không có trong CSV; nếu thiếu ngày cần thiết thì không thể chứng minh late claim.
- **Bằng chứng:** Delivery Agent có warning cho null timestamp và không tạo refund từ dữ liệu thiếu.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng:** Evidence hợp lệ về format nhưng một số chiến lược thêm evidence không liên quan làm điểm leaderboard giảm.
- **Nguyên nhân:** Evidence không chỉ cần tồn tại trong CSV mà còn phải liên quan trực tiếp đến root cause.
- **Cách xử lý:** Dùng evidence scope theo primary issue và chạy validator độc lập trước khi nộp.
- **Xác minh:** Các biến thể output đều được kiểm tra 50/50; chiến lược chính thức hiện tại có 50 output hợp lệ.
- **Bài học:** Không nên thêm toàn bộ entity vào evidence nếu không dùng để chứng minh kết luận.

## 7. Hiểu biết về luồng end-to-end

1. Dữ liệu từ CSV được DataStore index hóa; Delivery Agent nhận order record và item records từ Coordinator.
2. Delivery kết luận delivery status và seller handoff, sau đó Policy Agent chọn root cause.
3. Verifier kiểm tra output sau Policy Agent trước khi file được ghi.
4. Regression tests và validator dùng cùng contract để so sánh baseline, các bản sửa và output cuối.
5. Repair thành công khi không có validation error, đủ 50 file, evidence tồn tại, tiền/refund đúng và tests passed.

## 8. Cam kết

- [x] Nội dung phản ánh phần delivery, verifier và testing đã thực hiện.
- [x] Có thể giải thích luồng end-to-end.
- [x] Không ghi nhận kết quả chưa được kiểm chứng.
- [x] Không chứa secret.
- [x] Không sao chép nguyên văn báo cáo khác.

**Họ và tên:** Nguyễn Phương Linh  
**Ngày xác nhận:** 2026-08-05
