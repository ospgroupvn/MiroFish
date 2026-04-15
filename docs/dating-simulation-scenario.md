# Dating Simulation - Kịch bản mô phỏng 1 năm

## Tổng quan

Kịch bản này mô phỏng cuộc sống và tương tác của 2 đối tượng trong 5 năm, với tốc độ gia tốc (mỗi ngày thực tế = 1 tuần trong simulation). Simulation được thiết kế để chạy trên nền tảng MiroFish với multi-agent system.

---

## Cấu trúc Simulation

### Thời gian
- **Tổng thời gian mô phỏng:** 260 tuần (5 năm)
- **Tốc độ gia tốc:** 1 ngày thực = 1 tuần simulation
- **Tổng thời gian chạy thực tế:** ~260 ngày (nếu chạy liên tục)
- **Hoặc chạy nhanh:** 1 giờ thực = 1 tháng simulation (có thể tùy chỉnh)

### Nền tảng tương tác
- **Giai đoạn 1-3:** Hẹn hò trực tiếp, nhắn tin, gọi điện
- **Giai đoạn 4-6:** Tương tác mạng xã hội, gặp gỡ bạn bè
- **Giai đoạn 7-12:** Sống chung (tùy chọn), tương tác hàng ngày

---

## Các giai đoạn Simulation

### Giai đoạn 1: Làm quen (Tuần 1-12)

**Mục tiêu:** Tìm hiểu cơ bản về nhau

**Sự kiện chính:**
- Tuần 1-2: Cuộc hẹn đầu tiên (ăn tối, cafe)
- Tuần 3-4: Nhắn tin hàng ngày, gọi điện
- Tuần 5-6: Cuộc hẹn thứ 2 (hoạt động giải trí)
- Tuần 7-8: Thảo luận về sở thích, công việc
- Tuần 9-10: Gặp gỡ bạn bè thân
- Tuần 11-12: Thảo luận về giá trị, mục tiêu

**Chỉ số theo dõi:**
- Tần suất liên lạc (số tin nhắn/cuộc gọi mỗi ngày)
- Mức độ cởi mở在 giao tiếp
- Sự tương đồng trong sở thích

**Biến cố có thể xảy ra:**
- Một trong hai hủy hẹn phút chót
- Nhầm lẫn trong nhắn tin
- Phát hiện khác biệt lớn về sở thích

---

### Giai đoạn 2: Tìm hiểu sâu (Tuần 13-24)

**Mục tiêu:** Khám phá giá trị và tính cách

**Sự kiện chính:**
- Tuần 13-14: Thảo luận về gia đình, tuổi thơ
- Tuần 15-16: Gặp gỡ bạn bè thân
- Tuần 17-18: Thảo luận về mục tiêu tương lai
- Tuần 19-20: Chuyến đi ngắn cùng nhau (2-3 ngày)
- Tuần 21-22: Thảo luận về tài chính
- Tuần 23-24: Đánh giá 6 tháng đầu

**Chỉ số theo dõi:**
- Sự phù hợp về giá trị cốt lõi
- Khả năng hòa nhập với bạn bè đối phương
- Phong cách giải quyết mâu thuẫn (lần đầu cãi nhau)

**Biến cố có thể xảy ra:**
- Cãi nhau về vấn đề quan điểm
- Bạn bè không thích đối phương
- Phát hiện khác biệt về mục tiêu sống

---

### Giai đoạn 3: Gắn bó (Tuần 25-48)

**Mục tiêu:** Xây dựng sự thân mật và tin tưởng

**Sự kiện chính:**
- Tuần 25-28: Thảo luận về mối quan hệ (exclusive?)
- Tuần 29-32: Kỷ niệm đặc biệt (sinh nhật, ngày lễ)
- Tuần 33-36: Gặp gia đình đối phương
- Tuần 37-40: Tăng cường thời gian bên nhau
- Tuần 41-44: Chuyến đi dài ngày (1 tuần)
- Tuần 45-48: Đánh giá năm đầu tiên

**Chỉ số theo dõi:**
- Mức độ cam kết
- Sự thoải mái với gia đình đối phương
- Tần suất quan hệ tình dục (nếu có)
- Ngôn ngữ yêu thương được sử dụng

**Biến cố có thể xảy ra:**
- Gia đình không chấp nhận
- Xung đột về ranh giới cá nhân
- Vấn đề về sự ghen tuông

---

### Giai đoạn 4: Thử thách (Tuần 49-72)

**Mục tiêu:** Kiểm tra khả năng vượt qua khó khăn

**Sự kiện chính:**
- Tuần 49-52: Một trong hai gặp khó khăn (công việc, sức khỏe)
- Tuần 53-56: Thảo luận về tài chính
- Tuần 57-60: Chuyến đi dài ngày (1 tuần)
- Tuần 61-64: Đánh giá lại mối quan hệ
- Tuần 65-68: Thảo luận về sống chung
- Tuần 69-72: Đánh giá năm thứ 2

**Chỉ số theo dõi:**
- Khả năng hỗ trợ nhau trong khó khăn
- Sự phù hợp về quản lý tài chính
- Khả năng thỏa hiệp

**Biến cố có thể xảy ra:**
- Khó khăn tài chính
- Căng thẳng công việc ảnh hưởng đến quan hệ
- Phát hiện bí mật từ quá khứ

---

### Giai đoạn 5: Ổn định (Tuần 73-120)

**Mục tiêu:** Thiết lập nhịp điệu quan hệ

**Sự kiện chính:**
- Tuần 73-80: Bắt đầu sống chung (tùy chọn)
- Tuần 81-88: Điều chỉnh thói quen sinh hoạt
- Tuần 89-96: Phân chia việc nhà
- Tuần 97-104: Không gian cá nhân vs thời gian chung
- Tuần 105-112: Thảo luận về hôn nhân
- Tuần 113-120: Đánh giá năm thứ 3

**Chỉ số theo dõi:**
- Sự phù hợp trong sinh hoạt hàng ngày
- Phân chia việc nhà
- Không gian cá nhân vs thời gian chung

**Biến cố có thể xảy ra:**
- Xung đột về thói quen sinh hoạt
- Vấn đề về không gian cá nhân
- Căng thẳng vì sống chung

---

### Giai đoạn 6: Chuẩn bị hôn nhân (Tuần 121-180)

**Mục tiêu:** Lập kế hoạch hôn nhân, thảo luận con cái

**Sự kiện chính:**
- Tuần 121-130: Thảo luận chi tiết về hôn nhân
- Tuần 131-140: Thảo luận về con cái, timeline
- Tuần 141-150: Lập kế hoạch tài chính cho hôn nhân
- Tuần 151-160: Chuẩn bị tinh thần cho hôn nhân
- Tuần 161-170: Áp lực từ gia đình về hôn nhân
- Tuần 171-180: Đánh giá năm thứ 4

**Chỉ số theo dõi:**
- Sự phù hợp về timeline hôn nhân/con cái
- Mục tiêu dài hạn có tương thích không
- Mức độ hài lòng tổng thể

**Biến cố có thể xảy ra:**
- Khác biệt về quan điểm hôn nhân
- Không thống nhất về con cái
- Cơ hội công việc ở xa

---

### Giai đoạn 7: Hôn nhân và tương lai (Tuần 181-260)

**Mục tiêu:** Quyết định cuối cùng về hôn nhân, xây dựng tương lai

**Sự kiện chính:**
- Tuần 181-190: Quyết định kết hôn (nếu đạt ngưỡng)
- Tuần 191-200: Chuẩn bị đám cưới
- Tuần 201-210: Hôn nhân, điều chỉnh sau cưới
- Tuần 211-220: Lập kế hoạch 5 năm tiếp theo
- Tuần 221-230: Thảo luận về con cái cụ thể
- Tuần 231-240: Chuẩn bị cho con cái
- Tuần 241-250: Đánh giá 5 năm qua
- Tuần 251-260: Kế hoạch tương lai

**Chỉ số theo dõi:**
- Chỉ số ổn định (SI)
- Chỉ số phát triển (GT)
- Mức độ hài lòng hôn nhân
- Kế hoạch tương lai

**Biến cố có thể xảy ra:**
- Căng thẳng sau hôn nhân
- Vấn đề về con cái
- Khó khăn tài chính

---

## Hệ thống sự kiện ngẫu nhiên

### Sự kiện tích cực
- Nhận được thăng chức
- Được tăng lương
- Khỏi bệnh sau ốm
- Gặp lại bạn cũ
- Đạt được mục tiêu cá nhân

### Sự kiện tiêu cực
- Mất việc
- Ốm đau
- Gia đình có chuyện
- Tài chính khó khăn
- Xung đột với bạn bè

### Sự kiện trung tính
- Đi du lịch
- Thay đổi chỗ ở
- Học kỹ năng mới
- Thay đổi sở thích

---

## Metrics và Scoring System

### 1. Compatibility Score (CS) - Điểm phù hợp

**Công thức:**
```
CS = (GV * 0.30) + (PT * 0.25) + (GC * 0.20) + (LS * 0.15) + (MT * 0.10)
```

Trong đó:
- **GV (Core Values):** Điểm phù hợp giá trị cốt lõi (0-100)
- **PT (Personality Traits):** Điểm phù hợp tính cách (0-100)
- **GC (Communication):** Điểm phù hợp giao tiếp (0-100)
- **LS (Lifestyle):** Điểm phù hợp lối sống (0-100)
- **MT (Goals & Timeline):** Điểm phù hợp mục tiêu (0-100)

### 2. Relationship Health Score (RHS) - Sức khỏe mối quan hệ

**Chỉ số động, cập nhật hàng tuần:**
```
RHS = (SI * 0.20) + (TR * 0.25) + (CM * 0.20) + (PP * 0.15) + (SC * 0.20)
```

Trong đó:
- **SI (Sexual Intimacy):** Mức độ hài lòng tình dục (0-100)
- **TR (Trust & Respect):** Tin tưởng và tôn trọng (0-100)
- **CM (Conflict Management):** Quản lý xung đột (0-100)
- **PP (Positive Interactions):** Tương tác tích cực (0-100)
- **SC (Support & Care):** Hỗ trợ và quan tâm (0-100)

### 3. Stability Index (SI) - Chỉ số ổn định

**Đo lường khả năng duy trì mối quan hệ:**
```
SI = (CS * 0.40) + (RHS * 0.40) + (External_Factors * 0.20)
```

- **External Factors:** Áp lực từ gia đình, xã hội, tài chính (0-100)

### 4. Growth Trajectory (GT) - Xu hướng phát triển

**Đo lường mối quan hệ đang tốt lên hay xấu đi:**
```
GT = (RHS_current - RHS_4_weeks_ago) / RHS_4_weeks_ago * 100
```

- **GT > 0:** Mối quan hệ đang cải thiện
- **GT < 0:** Mối quan hệ đang suy giảm
- **GT = 0:** Ổn định

---

## Ngưỡng quyết định

### Tiếp tục mối quan hệ
- **CS >= 70** VÀ **RHS >= 65** VÀ **GT >= 0**

### Cần nỗ lực thêm
- **CS >= 60** VÀ **RHS >= 55** VÀ **GT < 0**
- Hoặc **CS >= 70** VÀ **RHS < 65**

### Nên chia tay
- **CS < 60** HOẶC **RHS < 55**
- Hoặc **GT < -15** (suy giảm nghiêm trọng)

### Kết hôn
- **CS >= 80** VÀ **RHS >= 75** VÀ **SI >= 60** VÀ **GT >= 5**
- Cả hai cùng muốn kết hôn

---

## Kịch bản mẫu cho MiroFish

### Prompt cho Simulation Engine

```
Bạn là một hệ thống mô phỏng mối quan hệ hẹn hò. Nhiệm vụ của bạn là tạo ra một thế giới song song nơi 2 agent (Person A và Person B) tương tác trong 5 năm.

**Profile của Person A:**
[Dán đầy đủ profile từ form ở trên]

**Profile của Person B:**
[Dán đầy đủ profile từ form ở trên]

**Thiết lập simulation:**
- Thời gian: 260 tuần (5 năm)
- Tốc độ: 1 ngày thực = 1 tuần simulation
- Nền tảng: Hẹn hò trực tiếp, nhắn tin, gọi điện, mạng xã hội
- Địa điểm: [Thành phố/Quốc gia cụ thể]

**Yêu cầu:**
1. Tạo ra các tình huống tương tác hàng tuần dựa trên profile của 2 agent
2. Mỗi agent phải hành xử nhất quán với tính cách, giá trị, và phong cách giao tiếp của mình
3. Đưa ra các biến cố ngẫu nhiên (tích cực, tiêu cực, trung tính) để thử thách mối quan hệ
4. Theo dõi và cập nhật các chỉ số CS, RHS, SI, GT hàng tuần
5. Tạo báo cáo chi tiết sau mỗi giai đoạn (7 giai đoạn)
6. Đưa ra dự đoán cuối cùng về khả năng thành công của mối quan hệ

**Output mong đợi:**
- Nhật ký tương tác hàng tuần
- Biểu đồ các chỉ số theo thời gian
- Phân tích các điểm phù hợp và không phù hợp
- Khuyến nghị cuối cùng (tiếp tục, nỗ lực thêm, hay chia tay)
```

---

## Báo cáo mẫu

### Báo cáo hàng tuần
```
Tuần [X]:
- Sự kiện chính: [mô tả]
- Tương tác: [số lần liên lạc, thời gian bên nhau]
- Xung đột: [có/không, mô tả]
- Chỉ số:
  * CS: [giá trị]
  * RHS: [giá trị]
  * SI: [giá trị]
  * GT: [giá trị]
- Nhận xét: [phân tích ngắn]
```

### Báo cáo giai đoạn
```
Giai đoạn [X]: [Tên giai đoạn]

**Tổng quan:**
- Điểm nổi bật:
- Thử thách chính:
- Bài học rút ra:

**Chỉ số:**
- CS trung bình: [giá trị]
- RHS trung bình: [giá trị]
- Xu hướng: [tăng/giảm/ổn định]

**Phân tích chi tiết:**
- Giá trị cốt lõi: [đánh giá]
- Tính cách: [đánh giá]
- Giao tiếp: [đánh giá]
- Lối sống: [đánh giá]
- Mục tiêu: [đánh giá]

**Khuyến nghị:**
- Tiếp tục theo dõi
- Cần cải thiện: [khía cạnh cụ thể]
- Cảnh báo: [nếu có]
```

### Báo cáo cuối năm
```
TỔNG KẾT MỐI QUAN HỆ 5 NĂM

**Điểm số cuối cùng:**
- Compatibility Score: [giá trị] - [mức độ]
- Relationship Health Score: [giá trị] - [mức độ]
- Stability Index: [giá trị] - [mức độ]
- Growth Trajectory: [giá trị] - [xu hướng]

**Phân tích tổng thể:**
- Điểm mạnh: [liệt kê]
- Điểm yếu: [liệt kê]
- Yếu tố quyết định: [yếu tố quan trọng nhất]

**Dự đoán:**
- Khả năng tiến đến hôn nhân: [cao/trung bình/thấp]
- Thời gian dự kiến: [nếu có]
- Rủi ro: [các rủi ro tiềm ẩn]

**Khuyến nghị cuối cùng:**
[Chi tiết và có căn cứ]
```

---

## Hướng dẫn triển khai trên MiroFish

### Bước 1: Chuẩn bị dữ liệu
1. Thu thập profile của 2 đối tượng từ form
2. Chuyển đổi profile thành agent configuration
3. Xác định các tham số simulation (tốc độ, địa điểm, v.v.)

### Bước 2: Cấu hình MiroFish
1. Tạo project mới: "Dating Simulation - [Tên A] & [Tên B]"
2. Upload profile như seed data
3. Cấu hình ontology cho dating domain
4. Thiết lập các agent với personality traits từ profile

### Bước 3: Chạy simulation
1. Bắt đầu với tốc độ chậm (1 ngày = 1 tuần) để quan sát
2. Theo dõi dashboard để điều chỉnh tham số
3. Ghi lại các sự kiện quan trọng
4. Chạy báo cáo sau mỗi giai đoạn

### Bước 4: Phân tích kết quả
1. Xem xét các báo cáo giai đoạn
2. Phân tích biểu đồ xu hướng
3. Đánh giá lại nếu cần điều chỉnh profile
4. Tạo báo cáo cuối cùng

---

## Lưu ý quan trọng

1. **Tính xác thực:** Agent phải hành xử nhất quán với profile, không được "diễn" theo kịch bản định sẵn
2. **Yếu tố ngẫu nhiên:** Cần có đủ biến cố để simulation không quá tuyến tính
3. **Đa chiều:** Đánh giá từ nhiều góc độ (cá nhân, xã hội, gia đình)
4. **Bảo mật:** Dữ liệu profile cần được bảo vệ
5. **Đạo đức:** Simulation chỉ mang tính chất tham khảo, không thay thế quyết định thực tế
