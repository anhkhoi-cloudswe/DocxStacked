import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Dict, List, Optional
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.app.core.config import get_settings
from backend.app.modules.analysis.ai_check import get_ai_check_service
from backend.app.modules.analysis.providers import VisionProvider, ProviderAuthError

settings = get_settings()


def evaluate_single_provider(
    provider: VisionProvider,
    eval_dir: Path,
    limit_per_subject: Optional[int] = None,
    force_refresh: bool = False,
) -> Optional[Dict]:
    """
    Evaluate accuracy of a single vision provider on MLN122 and PRN232 ground truth.
    Reports:
      - Total questions
      - Overall accuracy %
      - Separate accuracy for MLN122 and PRN232
      - List of mismatches with copied images in data/eval/mismatches/
      - Total calls count and errors count
    """
    if not provider.is_available():
        print(f"\n[!] BỎ QUA '{provider.name}': Chưa cấu hình {provider.api_key_env} trong .env hoặc hệ thống.")
        return None

    mismatches_dir = eval_dir / "mismatches"
    mismatches_dir.mkdir(parents=True, exist_ok=True)

    ai_service = get_ai_check_service()

    subjects = ["MLN122", "PRN232"]
    subject_results = {}
    all_mismatches = []

    total_correct = 0
    total_tested = 0
    total_errors = 0
    total_calls = 0
    cache_hits = 0

    print("\n" + "=" * 70)
    print(f"BẮT ĐẦU ĐÁNH GIÁ PROVIDER: {provider.name.upper()} (Model: {provider.model})")
    print("=" * 70)

    for sub in subjects:
        sub_dir = eval_dir / sub
        gt_file = sub_dir / "ground_truth.json"
        if not gt_file.exists():
            print(f"Không tìm thấy file ground truth: {gt_file}")
            continue

        with open(gt_file, "r", encoding="utf-8") as f:
            pairs = json.load(f)

        valid_pairs = [p for p in pairs if p.get("expected_answer") in ("A", "B", "C", "D")]
        if limit_per_subject:
            valid_pairs = valid_pairs[:limit_per_subject]

        print(f"\n--- Đang đánh giá môn {sub} ({len(valid_pairs)} câu hỏi A-D) ---")

        sub_correct = 0
        sub_wrong = 0
        sub_errors = 0
        sub_mismatches = []

        for p in valid_pairs:
            idx = p["index"]
            img_path = Path(p["image_path"])
            expected = p["expected_answer"]

            if not img_path.exists():
                print(f"  [{idx:02d}] Thiếu ảnh: {img_path.name}")
                sub_errors += 1
                total_errors += 1
                continue

            # Check cache status for call accounting
            phash = ai_service.compute_phash(img_path)
            cache_key = ai_service._get_cache_key(provider, phash)
            is_cached = (cache_key in ai_service._cache) and not force_refresh

            if is_cached:
                cache_hits += 1
            else:
                total_calls += 1

            try:
                res = ai_service.analyze_with_provider(provider, img_path, force_refresh=force_refresh)
            except ProviderAuthError as auth_err:
                print(f"\n[!] LỖI XÁC THỰC 401 trên '{provider.name}': Khóa {provider.api_key_env} không hợp lệ hoặc đã hết hạn.")
                print(f"    Chi tiết: {auth_err}")
                print(f"    Dừng đánh giá provider '{provider.name}'.")
                return None

            if not res or not res.answers:
                print(f"  [{idx:02d}] Lỗi gọi API / Sai format JSON (Kỳ vọng: {expected})")
                sub_errors += 1
                total_errors += 1
                continue

            ai_pred = res.answers[0].upper()
            is_match = (ai_pred == expected)

            kw = res.options.get(ai_pred, "")
            kw_display = f" | từ khoá: '{kw}'" if kw else ""

            if is_match:
                sub_correct += 1
                total_correct += 1
                print(f"  [{idx:02d}] ĐÚNG! Kỳ vọng: {expected} | AI: {ai_pred}{kw_display}")
            else:
                sub_wrong += 1
                print(f"  [{idx:02d}] SAI! Kỳ vọng: {expected} | AI: {ai_pred}{kw_display}")

                # Copy mismatch image
                dest_img_name = f"{provider.name}_{sub}_q{idx:03d}_exp_{expected}_ai_{ai_pred}.png"
                dest_img_path = mismatches_dir / dest_img_name
                try:
                    shutil.copy2(img_path, dest_img_path)
                except Exception:
                    pass

                mismatch_record = {
                    "subject": sub,
                    "index": idx,
                    "image_file": str(img_path.name),
                    "mismatch_image": dest_img_name,
                    "expected": expected,
                    "ai_prediction": ai_pred,
                    "full_answer_text": p.get("full_answer_text", ""),
                    "ai_options": res.options,
                    "ai_confidence": res.confidence,
                }
                sub_mismatches.append(mismatch_record)
                all_mismatches.append(mismatch_record)

        sub_tested = sub_correct + sub_wrong
        total_tested += sub_tested
        sub_acc = round((sub_correct / sub_tested * 100), 2) if sub_tested > 0 else 0.0

        subject_results[sub] = {
            "total_questions": len(valid_pairs),
            "tested": sub_tested,
            "correct": sub_correct,
            "wrong": sub_wrong,
            "errors": sub_errors,
            "accuracy_percent": sub_acc,
            "mismatches": sub_mismatches,
        }

    overall_acc = round((total_correct / total_tested * 100), 2) if total_tested > 0 else 0.0

    report = {
        "provider": provider.name,
        "model": provider.model,
        "api_key_env": provider.api_key_env,
        "total_tested": total_tested,
        "total_correct": total_correct,
        "total_wrong": len(all_mismatches),
        "total_errors": total_errors,
        "overall_accuracy_percent": overall_acc,
        "calls_count": total_calls,
        "cache_hits": cache_hits,
        "subject_breakdown": {
            sub: {
                "tested": data["tested"],
                "correct": data["correct"],
                "wrong": data["wrong"],
                "errors": data["errors"],
                "accuracy_percent": data["accuracy_percent"],
            }
            for sub, data in subject_results.items()
        },
        "mismatches": all_mismatches,
    }

    # Save individual report
    provider_report_path = eval_dir / f"evaluation_report_{provider.name}.json"
    with open(provider_report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Print summary
    print("\n" + "=" * 70)
    print(f"KẾT QUẢ ĐÁNH GIÁ: {provider.name.upper()} ({provider.model})")
    print(f"  - Độ chính xác tổng thể: {overall_acc}% ({total_correct}/{total_tested} câu)")
    for sub, data in subject_results.items():
        print(f"  - Môn {sub}: {data['accuracy_percent']}% ({data['correct']}/{data['tested']} câu)")
    print(f"  - Số lần gọi API: {total_calls} (Cache hits: {cache_hits})")
    print(f"  - Số lỗi / thử lại: {total_errors}")
    print(f"  - Số câu sai: {len(all_mismatches)} câu (ảnh đã lưu tại data/eval/mismatches/)")
    print(f"  - File báo cáo chi tiết: {provider_report_path}")
    print("=" * 70 + "\n")

    return report


def run_evaluation(
    target_provider: str = "all",
    limit_per_subject: Optional[int] = None,
    force_refresh: bool = False,
):
    eval_dir = Path("data/eval")
    ai_service = get_ai_check_service()
    providers = ai_service.get_providers()

    if not providers:
        print("Lỗi: Không tìm thấy provider nào được cấu hình trong config.yaml!")
        return

    selected_providers = []
    target_clean = target_provider.strip().lower()

    if target_clean == "all":
        selected_providers = providers
    else:
        for p in providers:
            if target_clean in p.name.lower():
                selected_providers.append(p)
        if not selected_providers:
            available_names = [p.name for p in providers]
            print(f"Lỗi: Không tìm thấy provider '{target_provider}'. Các provider có sẵn: {available_names}")
            return

    combined_summary = {}
    any_ran = False

    for provider in selected_providers:
        report = evaluate_single_provider(
            provider=provider,
            eval_dir=eval_dir,
            limit_per_subject=limit_per_subject,
            force_refresh=force_refresh,
        )
        if report:
            combined_summary[provider.name] = report
            any_ran = True

    if not any_ran:
        print("\n" + "=" * 70)
        print("CẢNH BÁO: Chưa có provider nào có API key để thực hiện đánh giá!")
        print("Vui lòng điền các khóa API vào backend/.env hoặc .env:")
        for p in providers:
            print(f"  - {p.name}: {p.api_key_env}")
        print("=" * 70 + "\n")
        return

    # Update global evaluation_report.json
    global_report_path = eval_dir / "evaluation_report.json"
    with open(global_report_path, "w", encoding="utf-8") as f:
        json.dump(combined_summary, f, ensure_ascii=False, indent=2)
    print(f"Đã cập nhật báo cáo tổng hợp tại: {global_report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate Vision AI providers accuracy on ground truth")
    parser.add_argument(
        "--provider",
        type=str,
        default="all",
        help="Provider to evaluate (e.g. anthropic, gemini, openai_compatible, or all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of questions to evaluate per subject",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass pHash cache and re-query the provider API",
    )

    args = parser.parse_args()
    run_evaluation(
        target_provider=args.provider,
        limit_per_subject=args.limit,
        force_refresh=args.force_refresh,
    )
