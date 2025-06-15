# Hệ thống Quản lý Kho với QR Code

## Cài đặt
```bash
pip install -r requirements.txt
```

## Khởi tạo Database
```bash
python database/init_db.py
python database/add_users.py
```

## Thêm dữ liệu test (tùy chọn)
```bash
python database/add_test_data.py
python database/generate_qr_codes.py
```

## Chạy hệ thống
```bash
python app.py
```

Truy cập: http://localhost:5000

## Dữ liệu Test
Hệ thống bao gồm **66+ sản phẩm test** với specifications đa dạng thuộc các nhóm:

### 📦 Nhóm sản phẩm chính:
- **Pneumatic Components** (6): Linh kiện khí nén SMC
- **Sensors** (6): Cảm biến OMRON, Panasonic  
- **Motors** (6): Động cơ Mitsubishi AC/Servo
- **Cables** (6): Cáp điện, cáp mạng
- **Tools** (6): Dụng cụ Bosch, Stanley
- **Safety** (6): Thiết bị bảo hộ Ansell, MSA

### 🔬 Nhóm sản phẩm chuyên dụng:
- **Controllers** (2): PLC và HMI Mitsubishi
- **Measuring Tools** (2): Dụng cụ đo Mitutoyo
- **Advanced Materials** (2): Ceramic, Carbon Fiber
- **Fasteners** (2): Bu lông Titanium, Washer đặc biệt
- **Environmental Sensors** (2): Cảm biến nhiệt độ, áp suất
- **Optics** (2): Thấu kính, gương laser
- **Adhesives** (2): Keo dán cấu trúc, UV curing

### 🧪 Nhóm vật liệu cơ bản:
- **Bearings** (3): Vòng bi SKF
- **Belts** (3): Dây curoa Gates  
- **Lubricants** (3): Mỡ bôi trơn Shell
- **Cleaners** (3): Hóa chất làm sạch

### 🏷️ Phân loại theo ứng dụng:
- **Electronic**: Linh kiện điện tử, cảm biến, PLC
- **Mechanical**: Cơ khí, vòng bi, động cơ
- **Chemical**: Hóa chất, keo dán, mỡ bôi trơn
- **PPE**: Thiết bị bảo hộ lao động
- **Tool**: Dụng cụ cầm tay và đo lường

### 📋 Đặc điểm specifications:
- **Thông số kỹ thuật chi tiết**: Kích thước, điện áp, vật liệu, độ chính xác
- **Thông tin môi trường**: Nhiệt độ hoạt động, độ ẩm, áp suất
- **Chứng nhận tiêu chuẩn**: ANSI, ISO, IP ratings
- **Dữ liệu hiệu suất**: Tốc độ, mô-men, độ bền, thời gian đáp ứng

Mỗi sản phẩm có:
- **QR Code** tự động sinh với thông tin chi tiết
- **Dữ liệu inventory** cho 12 tháng (2024)
- **Lịch sử giao dịch** nhập/xuất kho
- **Thông tin nhà cung cấp** và vị trí lưu trữ
