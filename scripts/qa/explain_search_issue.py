"""
Script explaining why typing 'MLN122' into 'Tìm kiếm đề thi' yielded 0 results before the refactor.
"""
import sys

def explain_search_issue():
    print("=== GIẢI THÍCH LỖI TÌM KIẾM 'MLN122' TRONG 'TÌM KIẾM ĐỀ THI' ===")
    print()
    print("1. NGUỒN DỮ LIỆU CỦA Ô 'Tìm kiếm đề thi' (input-search-exams):")
    print("   - Trong extension/sidepanel.js (hàm filterAndRenderChondeExams), ô này chỉ lọc:")
    print("     const query = elInputSearchExams ? elInputSearchExams.value.trim().toLowerCase() : '';")
    print("     chondeState.exams.filter(exam => exam.title.toLowerCase().includes(query));")
    print("   - Nguồn dữ liệu hoàn toàn là mảng in-memory: `chondeState.exams`.")
    print()
    print("2. TRẠNG THÁI CỦA NGUỒN DỮ LIỆU LÚC ĐÓ:")
    print("   - Khi người dùng mới mở extension hoặc tab 'Chọn đề', `chondeState.exams` được khởi tạo là `[]` (rỗng).")
    print("   - Chỉ sau khi người dùng chọn một môn từ dropdown <select> và bấm nút 'Lấy đề' (fetchSubjectExams),")
    print("     thì API /api/subjects/{subject_id}/threads mới được gọi để nạp danh sách đề vào `chondeState.exams`.")
    print("   - Do đó, khi người dùng gõ 'MLN122' trực tiếp vào ô 'Tìm kiếm đề thi' mà chưa chọn môn và chưa bấm 'Lấy đề',")
    print("     nguồn dữ liệu `chondeState.exams` là RỖNG (`len == 0`).")
    print("   - Kết quả lọc trên danh sách rỗng đương nhiên là 0 kết quả.")
    print()
    print("3. BẢN CHẤT LỖI THIẾT KẾ UX:")
    print("   - Người dùng tưởng ô 'Tìm kiếm đề thi' là tìm kiếm môn học hoặc tìm toàn cục 406 môn.")
    print("   - Thực tế nó chỉ là bộ lọc đề con trong 1 môn đã tải sẵn.")
    print("   - Đồng thời danh sách 406 môn lại nằm trong thẻ <select> dropdown thuần, không có chức năng gõ tìm kiếm môn.")
    print()
    print("4. GIẢI PHÁP ĐƯỢC YÊU CẦU & THỰC HIỆN:")
    print("   - Khối 'Thêm đề khác': MỘT ô combobox kiêm tìm kiếm môn học.")
    print("   - Tải 406 môn 1 lần từ backend, lưu cache.")
    print("   - Hỗ trợ gõ 'mln' -> hiển thị dropdown gợi ý tối đa 8 môn (MLN111, MLN122, ...), khớp không dấu/hoa thường.")
    print("   - Chọn môn xong -> TỰ ĐỘNG tải danh sách đề (kèm spinner, bỏ nút 'Lấy đề').")
    print("   - Ô lọc đề thi nhỏ chỉ xuất hiện bên trong danh sách đề sau khi đã chọn môn.")
    print("==================================================================")

if __name__ == '__main__':
    explain_search_issue()
