#!/usr/bin/env python3
"""
scripts/refresh_fuexam_subjects.py
Script làm mới danh mục môn học fuexam.me từ giao diện dòng lệnh.

Cách dùng:
    python scripts/refresh_fuexam_subjects.py            # Quét và cập nhật data/subjects_fuexam.json
    python scripts/refresh_fuexam_subjects.py --dry-run  # Chỉ quét và in ra các môn mới/đổi tên, không ghi đè file
"""

import argparse
import json
from pathlib import Path
import sys

# Đảm bảo UTF-8 trên Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.crawler.fuexam_subjects import (
    ensure_bootstrap_file_exists,
    refresh_fuexam_subjects,
    load_subject_map,
)


def main():
    parser = argparse.ArgumentParser(description="Làm mới danh mục môn học fuexam.me")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ kiểm tra thay đổi, không lưu vào file")
    parser.add_argument("--delay", type=float, default=1.6, help="Độ trễ giữa các request (giây), mặc định 1.6")
    args = parser.parse_args()

    ensure_bootstrap_file_exists()
    print("=" * 70)
    print("   LÀM MỚI DANH MỤC MÔN HỌC FUEXAM.ME (DYNAMIC REFRESH)")
    print(f"   Độ trễ an toàn: {args.delay} giây/request | Chế độ: {'Dry-run' if args.dry_run else 'Lưu trực tiếp'}")
    print("=" * 70)

    result = refresh_fuexam_subjects(
        delay_seconds=args.delay,
        save_to_disk=not args.dry_run,
    )

    if not result.get("success"):
        print(f"\n[X] Thất bại: {result.get('error')}")
        sys.exit(1)

    diff = result["diff"]
    print(f"\n[+] Hoàn tất quét toàn bộ node kỳ học!")
    print(f"    - Tổng số môn ban đầu : {diff['total_old']}")
    print(f"    - Tổng số môn quét được: {diff['total_new']}")
    print(f"    - Số môn không đổi    : {diff['unchanged_count']}")

    if diff["added"]:
        print(f"\n[*] Môn mới phát hiện ({len(diff['added'])} môn):")
        for item in diff["added"]:
            print(f"    + [{item['code']}] {item['name']} ({item['term_group']}) -> {item['forum_url']}")

    if diff["renamed"]:
        print(f"\n[*] Môn đổi tên ({len(diff['renamed'])} môn):")
        for item in diff["renamed"]:
            print(f"    ~ [{item['code']}] '{item['old_name']}' -> '{item['new_name']}'")

    if diff["moved"]:
        print(f"\n[*] Môn chuyển kỳ học / đổi URL ({len(diff['moved'])} môn):")
        for item in diff["moved"]:
            print(f"    ~ [{item['code']}] {item['old_term']} -> {item['new_term']}")

    if diff["removed"]:
        print(f"\n[-] Môn không còn tìm thấy ({len(diff['removed'])} môn):")
        for item in diff["removed"]:
            print(f"    - [{item['code']}] {item['name']}")

    if not args.dry_run:
        print(f"\n[✓] Đã cập nhật tệp: data/subjects_fuexam.json")
    else:
        print(f"\n[i] Chế độ dry-run: Chưa thay đổi tệp dữ liệu.")


if __name__ == "__main__":
    main()
