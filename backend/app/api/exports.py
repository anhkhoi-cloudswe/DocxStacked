from datetime import datetime
from io import BytesIO
from pathlib import Path
import re
from typing import List, Optional, Tuple
import zipfile
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Job
from backend.app.db.session import get_db

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/exports", tags=["exports"])


def parse_subject_and_category(
    filename: str, fallback_subject: str = "EXAMS", fallback_type: str = "FE"
) -> Tuple[str, str]:
    """
    Classify a document into its Subject and Category:
    - Subject: e.g. PRM392, CSD202, AIL303M
    - Category: 'FE' (FE & RE are grouped together) vs 'PE'
    """
    base_name = Path(filename).name
    upper_name = base_name.upper()

    # Determine category: PE is separate; FE and RE (retake) are grouped together as FE
    if re.search(r'\bPE\b', upper_name) or "- PE" in upper_name or "_PE" in upper_name:
        category = "PE"
    else:
        category = "FE"

    # Match subject prefix, e.g. PRM392, CSD202, AIL303M
    match = re.match(r'^([A-Za-z]{2,5}\d{3}[A-Za-z]?)', base_name.strip())
    if match:
        subject = match.group(1).upper()
    else:
        parts = [p.strip() for p in base_name.split("-") if p.strip()]
        if parts and len(parts[0]) >= 3 and any(char.isdigit() for char in parts[0]):
            subject = parts[0].upper()
        else:
            subject = (fallback_subject or "EXAMS").upper()

    return subject, category


async def build_folder_zip_response(
    job_id: Optional[str] = None,
    subject: Optional[str] = None,
    exam_type: Optional[str] = None,
    paths: Optional[List[str]] = None,
    db: Optional[AsyncSession] = None,
) -> Response:
    output_dir = settings.OUTPUT_DIR
    target_paths: List[Path] = []
    fallback_sub = subject or "EXAMS"
    fallback_cat = exam_type or "FE"

    if job_id and db:
        stmt = select(Job).where(Job.job_id == job_id)
        res = await db.execute(stmt)
        job = res.scalar_one_or_none()
        if job:
            if not subject:
                fallback_sub = job.subject_code or fallback_sub
            if not exam_type:
                fallback_cat = job.exam_type or fallback_cat
            job_files = (job.details or {}).get("files", [])
            for jf in job_files:
                p_str = jf.get("path")
                if p_str:
                    clean_p = p_str.replace("\\", "/").lstrip("/")
                    full_p = (settings.BASE_DIR / clean_p).resolve()
                    if full_p.exists() and full_p.is_file() and full_p.is_relative_to(output_dir.resolve()):
                        if full_p not in target_paths:
                            target_paths.append(full_p)

    if paths:
        for p_str in paths:
            clean_p = p_str.replace("\\", "/").lstrip("/")
            full_p = (settings.BASE_DIR / clean_p).resolve()
            if full_p.exists() and full_p.is_file() and full_p.is_relative_to(output_dir.resolve()):
                if full_p not in target_paths:
                    target_paths.append(full_p)

    if not target_paths:
        if subject:
            sub_dir = output_dir / subject
            if sub_dir.exists():
                target_paths = [p for p in sub_dir.glob("*.docx") if p.is_file()] + [p for p in sub_dir.glob("*.zip") if p.is_file()]
        else:
            target_paths = [p for p in output_dir.rglob("*.docx") if p.is_file()]

    if not target_paths:
        raise HTTPException(status_code=404, detail="Không tìm thấy file nào để nén tải về.")

    # Build zip archive with folder structure
    buf = BytesIO()
    folder_names: List[str] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in target_paths:
            sub, cat = parse_subject_and_category(f.name, fallback_subject=fallback_sub, fallback_type=fallback_cat)
            folder_name = f"{sub}_{cat}"
            folder_names.append(folder_name)
            arcname = f"{folder_name}/{f.name}"
            zf.write(f, arcname=arcname)

    buf.seek(0)
    zip_bytes = buf.getvalue()

    unique_folders = sorted(list(set(folder_names)))
    if len(unique_folders) == 1:
        zip_filename = f"{unique_folders[0]}.zip"
    elif 1 < len(unique_folders) <= 3:
        zip_filename = f"{'_'.join(unique_folders)}.zip"
    else:
        zip_filename = f"DocxStacked_Folders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


class ExportFileOut(BaseModel):
    filename: str
    relative_path: str
    size_bytes: int
    size_formatted: str
    created_at: str
    download_url: str


def _format_size(size_bytes: int) -> str:
    """Format bytes to human readable string (KB / MB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


@router.get("", response_model=List[ExportFileOut])
async def list_exported_files():
    """List all generated .docx and .zip export files."""
    output_dir = settings.OUTPUT_DIR
    if not output_dir.exists():
        return []

    files: List[ExportFileOut] = []
    # Search for all docx and zip files inside data/output
    for path in sorted(output_dir.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_file() and path.suffix.lower() in (".docx", ".zip"):
            stat = path.stat()
            rel_path = str(path.relative_to(settings.BASE_DIR)).replace("\\", "/")
            created_iso = datetime.fromtimestamp(stat.st_mtime).isoformat()
            files.append(
                ExportFileOut(
                    filename=path.name,
                    relative_path=rel_path,
                    size_bytes=stat.st_size,
                    size_formatted=_format_size(stat.st_size),
                    created_at=created_iso,
                    download_url=f"/api/exports/download?path={rel_path}",
                )
            )

    return files


@router.get("/download-folder")
async def download_folder_endpoint(
    job_id: Optional[str] = Query(None, description="Optional job ID to download files for"),
    subject: Optional[str] = Query(None, description="Optional subject code to download files for"),
    type: Optional[str] = Query(None, description="Optional exam type (FE/PE)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Download all compiled documents organized into structured folder(s) inside a zip.
    FE and RE files are grouped into {SUBJECT}_FE/, and PE into {SUBJECT}_PE/.
    """
    return await build_folder_zip_response(job_id=job_id, subject=subject, exam_type=type, db=db)


@router.get("/bundle.zip")
async def download_bundle_zip(job_id: Optional[str] = None):
    """
    Download a zip bundle containing all exported documents.
    If job_id is specified, bundles files for that job.
    """
    output_dir = settings.OUTPUT_DIR
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="No export files available to bundle")

    # Collect files
    target_files = [p for p in output_dir.rglob("*.docx") if p.is_file()]
    if not target_files:
        raise HTTPException(status_code=404, detail="No exported .docx files found to bundle")

    # Create zip in memory
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in target_files:
            rel_arcname = str(f.relative_to(output_dir)).replace("\\", "/")
            zf.write(f, arcname=rel_arcname)

    buf.seek(0)
    zip_bytes = buf.getvalue()
    bundle_filename = f"DocxStacked_Bundle_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{bundle_filename}"'},
    )


@router.get("/download")
async def download_export_file(
    path: Optional[str] = Query(None, description="Relative path of file to download"),
    file: Optional[str] = Query(None, description="Alternative param name for relative path"),
):
    """
    Download an exported document.
    Enforces strict path traversal safety: file MUST be inside settings.OUTPUT_DIR (data/output).
    """
    target = path or file
    if not target:
        raise HTTPException(status_code=400, detail="Missing required query parameter: path or file")
    try:
        out_resolved = settings.OUTPUT_DIR.resolve()
        target_str = target.replace("\\", "/")

        if target_str.startswith("data/") or ".." in target_str or target_str.startswith("/"):
            resolved_path = (settings.BASE_DIR / target_str.lstrip("/")).resolve()
        else:
            resolved_path = (out_resolved / target).resolve()

        # Enforce path traversal check: strictly inside OUTPUT_DIR
        try:
            is_inside = resolved_path.is_relative_to(out_resolved) and resolved_path != out_resolved
        except AttributeError:
            is_inside = str(resolved_path).startswith(str(out_resolved)) and resolved_path != out_resolved

        if not is_inside:
            logger.warning(f"Attempted path traversal access outside output directory: {target}")
            raise HTTPException(status_code=403, detail="Access denied: path must be inside output directory")

        if not resolved_path.exists() or not resolved_path.is_file():
            raise HTTPException(status_code=404, detail="Requested file does not exist")

        filename = resolved_path.name
        media_type = (
            "application/zip"
            if filename.endswith(".zip")
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        return FileResponse(
            path=str(resolved_path),
            filename=filename,
            media_type=media_type,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download file error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


class OpenFolderRequest(BaseModel):
    subject: Optional[str] = None
    path: Optional[str] = None


@router.post("/open-folder")
async def open_local_folder(req: Optional[OpenFolderRequest] = None):
    """
    Open the local output folder in Windows File Explorer (or default file manager).
    Supports opening the root output folder or a specific subject folder.
    """
    import os
    import subprocess
    import platform

    output_dir = settings.OUTPUT_DIR
    target_dir = output_dir

    if req and req.subject:
        cand = output_dir / req.subject
        if cand.exists() and cand.is_dir():
            target_dir = cand
    elif req and req.path:
        clean_p = req.path.replace("\\", "/").lstrip("/")
        cand = (settings.BASE_DIR / clean_p).resolve()
        if cand.exists():
            target_dir = cand if cand.is_dir() else cand.parent

    target_dir.mkdir(parents=True, exist_ok=True)
    abs_path = str(target_dir.resolve())

    try:
        if platform.system() == "Windows":
            os.startfile(abs_path)
        elif platform.system() == "Darwin":
            subprocess.run(["open", abs_path], check=False)
        else:
            subprocess.run(["xdg-open", abs_path], check=False)
        return {"success": True, "path": abs_path}
    except Exception as e:
        logger.error(f"Failed to open directory {abs_path}: {e}")
        return {"success": False, "error": str(e), "path": abs_path}
