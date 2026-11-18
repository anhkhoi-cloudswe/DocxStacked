import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from backend.app.modules.export.image_cropper import (
    crop_question_single,
    find_red_bar,
    text_mask,
    ImageCropConfig,
)

def inspect_exam_194():
    raw_dir = Path("data/raw/PRN232/exam_194_su25")
    q_indices = [1, 2, 3, 8, 31, 36]
    
    print("=== INSPECTING RAW IMAGES FOR PRN232 SU25 ===")
    results = {}
    cfg = ImageCropConfig()

    out_inspect_dir = Path("data/inspect_prn232")
    out_inspect_dir.mkdir(parents=True, exist_ok=True)

    annotated_images = []

    for q_idx in q_indices:
        # File name pattern: q{q_idx:02d}_*.webp or similar
        files = list(raw_dir.glob(f"q{q_idx:02d}_*.webp"))
        if not files:
            files = list(raw_dir.glob(f"q{q_idx:03d}_*.webp"))
        if not files:
            print(f"File not found for Q{q_idx}!")
            continue
        raw_file = files[0]
        im = Image.open(raw_file).convert("RGB")
        w, h = im.size
        arr = np.array(im)

        # Call existing cropper
        crop_res = crop_question_single(raw_file, config=cfg)
        
        # Check red bar
        bar = find_red_bar(arr)

        # Find true text bounds across the whole image (excluding navigation sidebar on left if any)
        # Let's inspect dark pixels in the question region
        # Looking at layout: sidebar on left, question in middle, or right?
        # Let's find columns with text
        # Dark pixels:
        dark_all = (arr.mean(axis=2) < 160) & ((arr.max(axis=2) - arr.min(axis=2)) < 50)
        
        # Current crop box in crop_res
        bx = crop_res.box # (x0, y0, x1, y1)

        # Let's inspect where actual question text is
        # Print info
        print(f"\n--- Q{q_idx} ({raw_file.name}) ---")
        print(f"Size: {w}x{h}")
        print(f"Red bar: {bar}")
        print(f"Layout detected: {crop_res.layout}")
        print(f"Cropper box: {bx} (width={bx[2]-bx[0]}, height={bx[3]-bx[1]})")
        print(f"Warnings: {crop_res.warnings}")

        # Let's check text distribution in horizontal slices and vertical columns
        # Where are the dark pixels?
        ys, xs = np.where(dark_all)
        # Filter out UI sidebar on left (x < 120) and top header (y < 40)
        content_mask = dark_all.copy()
        content_mask[:, :120] = False
        content_mask[:40, :] = False
        content_mask[h-30:, :] = False
        
        c_ys, c_xs = np.where(content_mask)
        if len(c_xs) > 0:
            real_x_min, real_x_max = int(c_xs.min()), int(c_xs.max())
            real_y_min, real_y_max = int(c_ys.min()), int(c_ys.max())
            print(f"Real text candidate bounds (excluding UI): x=[{real_x_min}, {real_x_max}], y=[{real_y_min}, {real_y_max}]")

        # Let's draw visual comparison on the image
        annotated = im.copy()
        draw = ImageDraw.Draw(annotated)
        # Green box = current cropper box
        draw.rectangle([bx[0], bx[1], bx[2], bx[3]], outline="green", width=4)
        if len(c_xs) > 0:
            # Red box = real content mask bounds
            draw.rectangle([real_x_min, real_y_min, real_x_max, real_y_max], outline="red", width=2)
        
        # Save individual annotated
        ann_path = out_inspect_dir / f"annotated_q{q_idx:02d}.png"
        annotated.save(ann_path)
        annotated_images.append((q_idx, annotated, bx, (real_x_min, real_y_min, real_x_max, real_y_max) if len(c_xs) > 0 else (0,0,0,0)))

    # Create contact sheet (ảnh ghép)
    # 6 images: 2 columns, 3 rows or 1 col 6 rows scaled down
    # Each image 1920x780 -> scale down to 960x390 for clarity
    thumb_w, thumb_h = 960, 390
    sheet = Image.new("RGB", (thumb_w * 2, thumb_h * 3 + 120), "white")
    sheet_draw = ImageDraw.Draw(sheet)
    
    # Title
    sheet_draw.rectangle([0, 0, thumb_w * 2, 40], fill="#1e293b")
    # Draw simple text
    # We can use default font
    for i, (q_idx, ann_im, cur_bx, real_bx) in enumerate(annotated_images):
        col = i % 2
        row = i // 2
        x_pos = col * thumb_w
        y_pos = 40 + row * (thumb_h + 25)
        
        thumb = ann_im.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (x_pos, y_pos))
        
        label = f"Q{q_idx:02d} | Cropper (Green): {cur_bx} | Real Content (Red): {real_bx}"
        sheet_draw.rectangle([x_pos, y_pos + thumb_h, x_pos + thumb_w, y_pos + thumb_h + 22], fill="#0f172a")
        sheet_draw.text((x_pos + 10, y_pos + thumb_h + 4), label, fill="white")

    sheet_path = out_inspect_dir / "contact_sheet_su25_boxes.png"
    sheet.save(sheet_path)
    print(f"\nSaved contact sheet to: {sheet_path}")

if __name__ == "__main__":
    inspect_exam_194()
