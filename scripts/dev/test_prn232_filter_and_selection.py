import sqlite3
import re

def test_prn232_filtering_and_selection():
    conn = sqlite3.connect("data/docxstacked.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, exam_type, url 
        FROM exams 
        WHERE subject_id=(SELECT id FROM subjects WHERE code='PRN232')
        ORDER BY id
    """)
    rows = cur.fetchall()
    conn.close()

    total_count = len(rows)
    print(f"Total PRN232 exams: {total_count}")
    assert total_count == 15, f"Expected 15 exams, got {total_count}"

    # Simulating extension getFilteredExams logic
    exams = []
    for r in rows:
        exams.append({
            "id": r[0],
            "title": r[1],
            "exam_type": r[2],
            "url": r[3]
        })

    def filter_exams(filter_type="ALL", query=""):
        q = query.strip().lower()
        filtered = []
        for ex in exams:
            if filter_type == "FE":
                is_fe = ex["exam_type"] == "FE" or bool(re.search(r"FE|RE", ex["title"], re.I))
                if not is_fe:
                    continue
            elif filter_type == "PE":
                is_pe = ex["exam_type"] == "PE" or bool(re.search(r"PE", ex["title"], re.I))
                if not is_pe:
                    continue
            if q:
                if q not in ex["title"].lower():
                    continue
            filtered.append(ex)
        return filtered

    # 1. ALL filter
    all_filtered = filter_exams("ALL")
    print(f"Filter ALL: {len(all_filtered)} exams")
    assert len(all_filtered) == 15

    # 2. FE-RE filter
    fe_filtered = filter_exams("FE")
    print(f"Filter FE-RE: {len(fe_filtered)} exams")
    for fe in fe_filtered:
        print(f"  - [{fe['id']}] {fe['title']} ({fe['exam_type']})")
    assert len(fe_filtered) == 4, f"Expected 4 FE-RE exams, got {len(fe_filtered)}"

    # 3. Simulate "Chọn tất cả" on FE-RE
    selected_urls = set(e["url"] for e in fe_filtered)
    assert len(selected_urls) == 4
    badge_selected = f"{len(selected_urls)} đã chọn"
    btn_start_queue = f"Soạn {len(selected_urls)} đề đã chọn"
    print(f"Badge: '{badge_selected}'")
    print(f"Queue button: '{btn_start_queue}'")
    assert badge_selected == "4 đã chọn"
    assert btn_start_queue == "Soạn 4 đề đã chọn"

    # 4. Switch to PE filter -> auto-deselect hidden
    pe_filtered = filter_exams("PE")
    print(f"Filter PE: {len(pe_filtered)} exams")
    assert len(pe_filtered) == 11

    visible_pe_urls = set(e["url"] for e in pe_filtered)
    for u in list(selected_urls):
        if u not in visible_pe_urls:
            selected_urls.remove(u)

    print(f"After switching to PE without selecting: {len(selected_urls)} selected")
    assert len(selected_urls) == 0

    # 5. Switch back to FE-RE, select 2 out of 4 -> indeterminate state
    fe_filtered = filter_exams("FE")
    selected_urls = set([fe_filtered[0]["url"], fe_filtered[1]["url"]])
    total_visible = len(fe_filtered)
    selected_visible = len(selected_urls)
    is_indeterminate = (0 < selected_visible < total_visible)
    print(f"Partial selection (2/4): indeterminate={is_indeterminate}")
    assert is_indeterminate is True

    print("\nALL SELECTION & FILTER TESTS PASSED!")

if __name__ == "__main__":
    test_prn232_filtering_and_selection()
