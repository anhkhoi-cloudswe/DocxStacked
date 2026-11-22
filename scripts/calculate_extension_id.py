#!/usr/bin/env python3
"""
scripts/calculate_extension_id.py

Tính toán Chrome / Edge Extension ID từ trường "key" trong manifest.json:
Thuật toán chuẩn Chromium:
1. Base64-decode chuỗi "key" để lấy bytes DER của RSA Public Key (SubjectPublicKeyInfo).
2. Tính mã băm SHA-256 trên chuỗi bytes DER này.
3. Lấy 32 ký tự hex đầu tiên (128 bits).
4. Ánh xạ từng ký tự hex (0-9, a-f) sang ký tự chữ thường (a-p):
   0 -> a (0 + ord('a'))
   ...
   9 -> j
   a -> k (10 + ord('a'))
   ...
   f -> p (15 + ord('a'))
5. So sánh với ID mục tiêu và in kết quả chi tiết.
"""

import base64
import hashlib
import json
from pathlib import Path

def calculate_extension_id_from_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {manifest_path}")

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    key_b64 = manifest_data.get("key")
    if not key_b64:
        raise ValueError(f"Không tìm thấy trường 'key' trong {manifest_path}")

    # 1. Base64 decode sang DER bytes
    der_bytes = base64.b64decode(key_b64)

    # 2. SHA-256 digest
    sha256_full = hashlib.sha256(der_bytes).hexdigest()

    # 3. Lấy 32 ký tự hex đầu
    first_32_hex = sha256_full[:32]

    # 4. Ánh xạ 0-f -> a-p
    calculated_id = "".join(chr(ord("a") + int(c, 16)) for c in first_32_hex)

    target_id = "kicplcdfmbcfjildbbimpfiljlmfokea"
    matches = (calculated_id == target_id)

    return {
        "manifest_path": str(manifest_path),
        "raw_key_length": len(key_b64),
        "sha256_full": sha256_full,
        "first_32_hex": first_32_hex,
        "calculated_id": calculated_id,
        "target_id": target_id,
        "matches": matches,
    }

if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    manifest_p = base_dir / "extension" / "manifest.json"
    result = calculate_extension_id_from_manifest(manifest_p)

    print("==================================================")
    print("KẾT QUẢ TÍNH EXTENSION ID TỪ KEY TRONG MANIFEST")
    print("==================================================")
    print(f"File manifest  : {result['manifest_path']}")
    print(f"SHA-256 (DER)  : {result['sha256_full']}")
    print(f"32 hex đầu     : {result['first_32_hex']}")
    print(f"Extension ID   : {result['calculated_id']}")
    print(f"ID mục tiêu    : {result['target_id']}")
    print(f"Khớp nhau      : {'CHÍNH XÁC (Trùng khớp 100%)' if result['matches'] else 'KHÔNG KHỚP'}")
    print("==================================================")
