# Báo cáo cá nhân — Đỗ Thái Dương

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
|---|---|
| Họ và tên | Đỗ Thái Dương |
| MSSV | 2A202601331 |
| Khóa/Lớp | K3 / D304 |
| Vai trò chính | Data Loader và Order/Payment Agent Engineer |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

| Module/deliverable | File/hàm phụ trách | Input | Output | Trạng thái |
|---|---|---|---|---|
| Nạp và index dữ liệu | `app/data_loader.py` / `OlistDataStore.load` | 8 CSV Olist | Index order, item, payment, seller | Hoàn thành |
| Order/Seller Agent | `app/agents/order_seller_agent.py` | `order_id` | Items, sellers, item/freight total | Hoàn thành |
| Payment Agent | `app/agents/payment_agent.py` | Order totals và payment rows | Payment total, IDs, reconciliation | Hoàn thành |

## 3. Kết quả theo vai trò

- Đọc dữ liệu bằng pandas và chuyển các row thành typed records.
- Index hóa theo `order_id`, giúp truy xuất nhiều item/payment trong cùng order.
- Tính `item_total` từ `price`, `freight_total` từ `freight_value` và `payment_total` từ `payment_value`.
- Kiểm tra reconciliation với sai số `0.10 BRL`.

Lệnh xác minh:

```bash
.venv/bin/python scripts/check_input.py
.venv/bin/python scripts/validate_outputs.py
```

Kết quả: đủ 50 input, 50 output verified thành công.

## 4. Giải thích phần kỹ thuật

### Vấn đề cần giải quyết

Olist có quan hệ một-nhiều: một order có thể có nhiều item, seller hoặc payment. Nếu chỉ lấy dòng đầu tiên sẽ làm sai tổng tiền, evidence và refund.

### Cách triển khai

`OlistDataStore` đọc các CSV, parse timestamp, chuyển số tiền sang `Decimal` và lưu các map theo khóa join. `OrderSellerAgent` lấy toàn bộ item của order rồi cộng giá và phí vận chuyển. `PaymentAgent` lấy toàn bộ payment row, giữ `payment_sequential` trong ID và đối chiếu tổng payment với item plus freight.

`payment_installments` chỉ là số kỳ trả góp và không được cộng vào tổng payment.

### Input, output và contract

| Thành phần | Mô tả |
|---|---|
| Input | CSV Olist trong `data/` và `order_id` |
| Output | `OrderSellerResult`, `PaymentResult` |
| Module phụ thuộc | `app/schemas.py`, `app/config.py` |
| Module sử dụng output | Coordinator, Policy Agent, Verifier |
| Điều kiện lỗi | Order không tồn tại, không có item/payment, số tiền null hoặc timestamp thiếu |

### Cách xác minh

```bash
.venv/bin/python -m pytest -q tests/test_agents.py tests/test_verifier.py
```

- Kết quả mong đợi: agent trả đúng tổng tiền và IDs.
- Kết quả thực tế: test suite hoàn thành; pipeline tạo 50 JSON hợp lệ.
- Artifact: `output/` và `logging/trace.jsonl`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Chọn cách tính tiền và reconciliation.
- **Phương án:** Dùng float trực tiếp hoặc dùng Decimal và chỉ round ở output.
- **Lựa chọn:** Decimal.
- **Lý do:** Tránh sai số floating point khi so sánh ngưỡng `0.10 BRL`; tổng được tính trên toàn bộ row rồi mới làm tròn 2 chữ số.
- **Bằng chứng:** Verifier kiểm tra item, freight và payment totals cho toàn bộ 50 output mà không có failure.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng:** Một số output có thể sai khi order chứa nhiều payment hoặc nhiều item.
- **Nguyên nhân:** Nếu dùng một row đầu tiên thay vì aggregate toàn bộ order, payment reconciliation và freight refund sẽ sai.
- **Cách xử lý:** Lưu list đầy đủ theo order, sort theo `order_item_id`/`payment_sequential` và cộng tất cả row.
- **Xác minh:** Unit tests cho multiple items/multiple payments và validator độc lập đều chạy qua.
- **Bài học:** Không được giả định quan hệ one-to-one trong dữ liệu Olist.

## 7. Hiểu biết về luồng end-to-end

1. Data loader đọc CSV và tạo index. Coordinator truyền `claimed_order_id` đến Order/Seller Agent.
2. Order/Seller Agent trả item, seller và tổng tiền; Payment Agent dùng tổng đó để reconciliation toàn bộ payment rows.
3. Delivery Agent đọc các timestamp giao hàng; Policy Agent dùng các kết quả đã handoff để chọn rule.
4. Cùng một bộ 50 input được dùng để tạo output, validate và chạy regression tests nhằm bảo đảm kết quả không đổi.
5. Repair được coi là thành công khi validator báo 50/50, các ID tồn tại, financial values đúng và test suite passed.

## 8. Cam kết

- [x] Nội dung phản ánh phần data loading và payment/order đã thực hiện.
- [x] Có thể giải thích luồng end-to-end.
- [x] Không ghi nhận kết quả chưa được kiểm chứng.
- [x] Không chứa secret.
- [x] Không sao chép nguyên văn báo cáo khác.

**Họ và tên:** Đỗ Thái Dương  
**Ngày xác nhận:** 2026-08-05
