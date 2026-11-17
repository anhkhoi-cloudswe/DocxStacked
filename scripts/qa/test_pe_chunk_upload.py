"""
QA Test for Part E:
Mock PE exam with 2 files (PDF 1MB, ZIP 30MB).
Uploads via chunked endpoint /api/ingest/pe-upload-chunk and verifies byte size on disk.
"""
import os
import sys
import time
import base64
import requests

BACKEND_URL = "http://127.0.0.1:8000"
CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB

def generate_mock_file(path, size_bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        chunk = b"A" * (1024 * 1024)
        written = 0
        while written < size_bytes:
            to_write = min(len(chunk), size_bytes - written)
            f.write(chunk[:to_write])
            written += to_write

def test_pe_upload():
    print("=== TEST PART E: PE EXAM CHUNKED UPLOAD ===")
    mock_dir = "temp_mock_pe"
    pdf_path = os.path.join(mock_dir, "paper.pdf")
    zip_path = os.path.join(mock_dir, "materials.zip")

    pdf_size = 1024 * 1024       # 1 MB
    zip_size = 30 * 1024 * 1024  # 30 MB

    print(f"Creating mock files: PDF ({pdf_size} bytes), ZIP ({zip_size} bytes)...")
    generate_mock_file(pdf_path, pdf_size)
    generate_mock_file(zip_path, zip_size)

    subject_code = "PRM392"
    exam_title = "PRM392_PE_SU24_PRACTICAL"

    files_to_upload = [
        ("paper.pdf", pdf_path, pdf_size),
        ("materials.zip", zip_path, zip_size),
    ]

    headers = {
        "X-DocxStacked-Ext": "kicplcdfmbcfjildbbimpfiljlmfokea"
    }

    total_start = time.time()
    for filename, local_path, expected_size in files_to_upload:
        file_start = time.time()
        print(f"\n--- Uploading {filename} ({expected_size / (1024*1024):.2f} MB) ---")

        with open(local_path, "rb") as f:
            file_bytes = f.read()

        total_chunks = (len(file_bytes) + CHUNK_SIZE - 1) // CHUNK_SIZE
        print(f"Total chunks ({CHUNK_SIZE / (1024*1024):.0f} MB each): {total_chunks}")

        for c_idx in range(total_chunks):
            start = c_idx * CHUNK_SIZE
            end = min(start + CHUNK_SIZE, len(file_bytes))
            chunk_data = file_bytes[start:end]
            chunk_b64 = "data:application/octet-stream;base64," + base64.b64encode(chunk_data).decode("utf-8")

            payload = {
                "subject_code": subject_code,
                "exam_title": exam_title,
                "file_name": filename,
                "chunk_index": c_idx,
                "total_chunks": total_chunks,
                "chunk_base64": chunk_b64
            }

            resp = requests.post(f"{BACKEND_URL}/api/ingest/pe-upload-chunk", json=payload, headers=headers, timeout=60)
            if resp.status_code != 200:
                print(f"Error chunk {c_idx}: {resp.status_code} {resp.text}")
                sys.exit(1)
            else:
                print(f"Chunk {c_idx + 1}/{total_chunks} uploaded successfully ({len(chunk_data)} bytes).")

        file_elapsed = time.time() - file_start
        print(f"Uploaded {filename} in {file_elapsed:.2f}s")

    total_elapsed = time.time() - total_start
    print(f"\nAll uploads completed in {total_elapsed:.2f}s")

    # Verify on disk
    dest_dir = os.path.join("data", "output", subject_code, f"{subject_code}_PE", exam_title)
    print(f"\nVerifying files in disk folder: {dest_dir}")
    if not os.path.isdir(dest_dir):
        print(f"ERROR: Destination directory does not exist: {dest_dir}")
        sys.exit(1)

    for filename, _, expected_size in files_to_upload:
        disk_file = os.path.join(dest_dir, filename)
        if not os.path.exists(disk_file):
            print(f"ERROR: File missing on disk: {disk_file}")
            sys.exit(1)
        actual_size = os.path.getsize(disk_file)
        print(f"- {filename}: Expected={expected_size} bytes, Actual on disk={actual_size} bytes -> {'MATCH' if actual_size == expected_size else 'MISMATCH'}")
        if actual_size != expected_size:
            print(f"ERROR: Size mismatch for {filename}!")
            sys.exit(1)

    # Clean up mock source files
    for p in [pdf_path, zip_path]:
        if os.path.exists(p):
            os.remove(p)
    if os.path.exists(mock_dir):
        os.rmdir(mock_dir)

    print("\n[PART E TEST PASSED] All PE files uploaded and matched bit-for-bit!")

if __name__ == "__main__":
    test_pe_upload()
