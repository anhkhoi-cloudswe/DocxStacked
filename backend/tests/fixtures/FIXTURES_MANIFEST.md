# Danh mục & Hướng dẫn Quản lý Test Fixtures

Tài liệu này đánh dấu và phân loại các fixtures dùng trong kiểm thử tự động của hệ thống `DocxStacked`.

## 1. Phân loại Fixtures

### A. Fixtures tổng hợp (Synthetic Fixtures)
- Các file HTML và ảnh được sinh nhân tạo bằng code mô phỏng cấu trúc của XenForo hoặc layout đề thi mà không chứa dữ liệu thi thực tế:
  - `test_vision_probe.png`: Ảnh 50x50 vẽ chữ cái kiểm tra kết nối API.
  - Các mock fixtures trong `backend/tests/test_ai_mock_suite.py`: Ảnh synthetic dạng bytearray/PIL Image tạo trực tiếp trong runtime bộ test.

### B. Fixtures mẫu kiểm thử độ chính xác (Reference Crop Fixtures)
- Thư mục `backend/tests/fixtures/crop/`:
  - Chứa các ảnh mẫu crop kích thước nhỏ (~20KB - 150KB) được dùng để unit test thuật toán cắt bỏ viền đỏ (`test_image_cropper_layout.py`) và kiểm thử trích xuất ký tự đáp án AI (`test_ai_cascade.py`).
  - **Lưu ý bảo mật & bản quyền:**
    - Toàn bộ ảnh gốc toàn màn hình (`data/raw/`) và ảnh crop thực tế (`data/cropped/`) đã được cấu hình trong `.gitignore` để **tuyệt đối không commit** lên Git repository.
    - Các file trong `backend/tests/fixtures/crop/` chỉ phục vụ kiểm thử hồi quy độ chính xác của bounding box và viền panel, không chứa thông tin định danh thí sinh, giáo viên hay tài khoản đăng nhập.

## 2. Cách sinh Fixture tổng hợp (Synthetic Crop Generator)
Nếu cần bổ sung fixture mà không dùng ảnh thật, có thể chạy đoạn script sau:
```python
from PIL import Image, ImageDraw, ImageFont

def make_synthetic_crop(path, text="Question 1: What is polymorphism?"):
    img = Image.new("RGB", (600, 300), color="white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([5, 5, 595, 295], outline="gray", width=2)
    draw.text((20, 30), text, fill="black")
    draw.text((30, 80), "A. Inheritance", fill="black")
    draw.text((30, 120), "B. Encapsulation", fill="black")
    draw.text((30, 160), "C. Multiple forms", fill="black")
    draw.text((30, 200), "D. Abstraction", fill="black")
    img.save(path)
```
