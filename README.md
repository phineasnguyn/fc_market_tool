# FC Market Clicker (Auto TTCN FC Online)

Ứng dụng Windows hỗ trợ theo dõi, chèn lệnh mua và chèn lệnh bán cầu thủ tự động trên Thị trường chuyển nhượng (TTCN) của tựa game **FC Online**. Hỗ trợ chạy nền không chiếm con trỏ chuột và tự động nhận diện giá/hàng đợi bằng OCR (Tesseract).

---

## 🌟 Tính Năng Nổi Bật

- **Chèn Mua / Chèn Bán Tự Động theo điều kiện:**
  - **Chèn mua (Giá trần):** Tự động chọn mức giá tối đa và xác nhận mua.
  - **Chèn bán (Giá sàn):** Tự động bắt giá sàn thấp nhất để thoát hàng nhanh khi thị trường biến động.
  - **Chèn bán (Giá trần):** Tự động bắt giá tối đa khi cần chèn vị trí bán đầu tiên.
  - **Cơ chế kiểm soát hàng đợi:** Dừng hoặc hủy khi số lệnh đặt trước $\le$ mức cài đặt (giành vị trí ưu tiên đầu hàng). Tự động đặt lệnh tiếp khi thị trường vừa reset giá.
  - **Tự động thử lại (Retry):** Bền bỉ vượt qua lag, nghẽn mạng hoặc độ trễ tải dữ liệu từ game.
- **Chế độ Chạy Nền (thử nghiệm, không chiếm chuột):**
  - Chụp riêng cửa sổ game và gửi tín hiệu click qua Win32 API (`PostMessage`). Chế độ này mặc định tắt vì vẫn cần kiểm tra trực tiếp xem FC Online có nhận input nền trên từng máy hay không.
- **Auto-Click Chuỗi Phím Thủ Công:**
  - Hỗ trợ lưu danh sách tọa độ tùy ý (F6) và phát lại vòng lặp (F8).
- **Hỗ trợ Đa Độ Phân Giải (Chuẩn hóa 16:9):**
  - Tự động crop vùng game và quy đổi về tọa độ gốc 1920 × 1080.
  - Tự tìm vị trí nút Mua/Bán/Hủy theo màu để chịu được thay đổi vị trí theo chiều dọc giữa các giao diện.

---

## ⚙️ Yêu Cầu Hệ Thống

1. **Hệ điều hành:** Windows 10 / Windows 11 (64-bit).
2. **Quyền Administrator:** Game FC Online chạy dưới quyền Admin, do đó tool cũng bắt buộc chạy với quyền **Administrator** để gửi tín hiệu chuột và chụp cửa sổ game.
3. **Python:** Phiên bản 3.10 trở lên (nếu chạy mã nguồn).
4. **Tesseract OCR 5:**
   - Cài đặt [Tesseract OCR for Windows](https://github.com/UB-Mannheim/tesseract/wiki) (chọn ngôn ngữ `eng`).
   - Đường dẫn mặc định: `C:\Program Files\Tesseract-OCR\tesseract.exe` (hoặc cấu hình qua biến môi trường `TESSERACT_PATH`).

---

## 🚀 Cài Đặt & Sử Dụng

### Cách 1: Chạy trực tiếp từ mã nguồn Python

1. **Clone repository:**
   ```bash
   git clone https://github.com/phineasnguyn/fc_market_tool.git
   cd fc_market_tool
   ```

2. **Cài đặt thư viện phụ thuộc:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Khởi chạy ứng dụng (Chạy terminal với quyền Administrator):**
   ```bash
   python app.py
   # hoặc nhấp đúp file run.bat (với quyền Run as Administrator)
   ```

### Cách 2: Đóng gói thành file `.exe` độc lập

Dự án đã tích hợp sẵn file cấu hình PyInstaller:
```bash
pyinstaller FCMarketClicker.spec
```
File thực thi độc lập sẽ được tạo tại `dist/FCMarketClicker.exe`.

---

## 📖 Hướng Dẫn Sử Dụng Chi Tiết

### 1. Chèn Mua / Chèn Bán Tự Động

1. Trong FC Online, chuyển đến tab **TTCN → DS của bạn** (danh sách mua hoặc bán).
2. Mở ứng dụng, nhấn **F7** (hoặc bấm nút **Tìm FC Online**) để tự động nhận diện cửa sổ game.
3. Cài đặt các thông số:
   - **Chế độ hoạt động:** `Chèn mua (Giá trần)`, `Chèn bán (Giá sàn)`, hoặc `Chèn bán (Giá trần)`.
    - **Tên cầu thủ:** Nên nhập để bot đối chiếu tên trên hàng và trong hộp thao tác, tránh bấm nhầm khi danh sách đổi thứ tự.
   - **Vị trí hàng:** Thứ tự cầu thủ trong DS của bạn (từ 1 đến 5).
   - **Số lệnh xếp hàng phía trước tối đa:** Ngưỡng mốc để dừng/hoàn thành.
4. Bật chế độ **Mô phỏng** và nhấn **Kiểm tra màn hình game** để xác nhận OCR nhận diện chính xác giá và hàng đợi.
5. Bỏ chọn **Mô phỏng**, nhấn **Lưu cấu hình**.
6. Nhấn **F11** (hoặc nút **Bắt đầu chạy**) để tiến hành tự động. Nhấn **F9** để dừng khẩn cấp bất kỳ lúc nào.

Bot chỉ bấm đặt lệnh khi đọc được đầy đủ giá đăng ký, giá mục tiêu và số lượng hàng đợi. Nếu loại hộp Mua/Bán không khớp chế độ, tên cầu thủ không khớp hoặc OCR thiếu số lượng, bot đóng hộp/thử lại hoặc dừng thay vì bấm tiếp.

### 2. Phím Tắt Tiện Ích

| Phím tắt | Chức năng |
| :--- | :--- |
| **F6** | Ghi nhận tọa độ chuột hiện tại vào chuỗi click thủ công |
| **F7** | Tự động tìm kiếm và kết nối cửa sổ FC ONLINE |
| **F8** | Bắt đầu / Tạm dừng chuỗi click thủ công |
| **F9** | **Dừng khẩn cấp** toàn bộ hoạt động của bot |
| **F11** | Bắt đầu chạy bot chèn lệnh tự động |

---

## 📁 Cấu Trúc Dự Án

```
fc_market_tool/
├── app.py                     # Giao diện người dùng Tkinter & điều phối chính
├── engine.py                  # Bộ máy thực thi chuỗi click
├── market_bot.py              # State machine xử lý chu kỳ chèn lệnh mua/bán
├── vision.py                  # Xử lý hình ảnh, FastOcr qua ctypes và phân tích UI
├── windows.py                 # Tương tác Win32 API, chụp màn hình & click nền
├── test_market_bot.py         # Unit tests cho logic bot mua/bán
├── test_windows_background.py # Unit tests cho điều khiển nền Win32
├── run.bat                    # Script khởi chạy nhanh
├── FCMarketClicker.spec       # Cấu hình đóng gói PyInstaller
├── requirements.txt           # Danh sách thư viện Python phụ thuộc
└── README.md                  # Tài liệu hướng dẫn sử dụng
```

---

## ⚠️ Lưu Ý & Miễn Trừ Trách Nhiệm

- Ứng dụng chỉ tương tác qua việc đọc hình ảnh màn hình và gửi tín hiệu chuột, **không can thiệp vào bộ nhớ hay mã nguồn của game**.
- Chế độ chạy nền phụ thuộc việc game có chấp nhận thông điệp chuột Windows. Hãy kiểm tra bằng chế độ mô phỏng và quan sát nhật ký trước khi chạy thật.
- Công cụ được phát triển phục vụ mục đích học tập, nghiên cứu tự động hóa giao diện trên hệ điều hành Windows. Người dùng tự chịu trách nhiệm về mục đích sử dụng.
