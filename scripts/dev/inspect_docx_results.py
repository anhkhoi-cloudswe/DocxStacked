from docx import Document

def inspect_docx(path_str):
    doc = Document(path_str)
    print(f"\n=== Inspecting {path_str} ===")
    print(f"Total paragraphs: {len(doc.paragraphs)}")
    
    # Check questions & answers
    ans_paras = []
    missing_flags = []
    clipped_flags = []
    
    for i, p in enumerate(doc.paragraphs):
        t = p.text.strip()
        if t.startswith("Đáp án:"):
            ans_paras.append((i, t))
            if "ảnh nguồn thiếu phương án" in t:
                missing_flags.append((i, t))
            if "ảnh nguồn bị cụt" in t:
                clipped_flags.append((i, t))
                
    print(f"Answer paragraphs count: {len(ans_paras)}")
    print(f"Questions with 'ảnh nguồn thiếu phương án': {len(missing_flags)}")
    print(f"Questions with 'ảnh nguồn bị cụt': {len(clipped_flags)}")
    print("Sample answers:")
    for item in ans_paras[:5]:
        print(f"  {item[1]}")
    for item in ans_paras[20:25]:
        print(f"  {item[1]}")

if __name__ == "__main__":
    inspect_docx("data/output/PRN232/PRN232 - SU25 - Final Exam.docx")
    inspect_docx("data/output/PRN232/PRN232 - SU26 - B5 - FE.docx")
