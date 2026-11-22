from datetime import datetime
from io import BytesIO
from pathlib import Path
import re
from typing import List, Optional, Tuple
import zipfile
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Job
from backend.app.db.session import get_db

logger = get_logger(__name__)
class SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)

settings = SettingsProxy()

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


class _ChunkYieldingWriter:
    """Non-buffering stream writer for zipfile with tell() support."""
    def __init__(self):
        self.chunks = []
        self._pos = 0

    def write(self, b):
        if b:
            self.chunks.append(b)
            self._pos += len(b)
        return len(b)

    def tell(self):
        return self._pos

    def flush(self):
        pass

    def pop_chunks(self):
        c = self.chunks
        self.chunks = []
        return c


def stream_zip_files(files_with_arcnames: List[Tuple[Path, str]]):
    """
    Yields chunks of a zip archive on the fly using ZIP_STORED.
    Docx and zip files are already compressed, avoiding double compression and keeping RAM minimal.
    """
    writer = _ChunkYieldingWriter()
    with zipfile.ZipFile(writer, mode="w", compression=zipfile.ZIP_STORED) as zf:
        for c in writer.pop_chunks():
            yield c

        for fpath, arcname in files_with_arcnames:
            stat = fpath.stat()
            zinfo = zipfile.ZipInfo(arcname)
            zinfo.compress_type = zipfile.ZIP_STORED
            zinfo.file_size = stat.st_size
            zinfo.flag_bits = 0x08  # Bit 3: data descriptor for streaming

            with open(fpath, "rb") as src:
                with zf.open(zinfo, mode="w") as dest:
                    while chunk := src.read(64 * 1024):
                        dest.write(chunk)
                        for c in writer.pop_chunks():
                            yield c

            for c in writer.pop_chunks():
                yield c

    for c in writer.pop_chunks():
        yield c


async def build_folder_zip_response(
    job_id: Optional[str] = None,
    subject: Optional[str] = None,
    exam_type: Optional[str] = None,
    paths: Optional[List[str]] = None,
    db: Optional[AsyncSession] = None,
):
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

    # Filter out test artifacts and tiny placeholder files
    filtered_targets: List[Path] = []
    for p in target_paths:
        if p.stat().st_size < 50:
            continue
        p_u = p.name.upper()
        if "TEST" in p_u or "(EXTENSION INGESTED)" in p_u or p_u.endswith("TEST.DOCX"):
            continue
        filtered_targets.append(p)

    if not filtered_targets:
        filtered_targets = target_paths

    folder_names: List[str] = []
    files_with_arcnames: List[Tuple[Path, str]] = []

    for f in filtered_targets:
        sub, cat = parse_subject_and_category(f.name, fallback_subject=fallback_sub, fallback_type=fallback_cat)
        folder_name = f"{sub}_{cat}"
        folder_names.append(folder_name)
        arcname = f"{folder_name}/{f.name}"
        files_with_arcnames.append((f, arcname))

    unique_folders = sorted(list(set(folder_names)))
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    if len(unique_folders) == 1:
        zip_filename = f"{unique_folders[0]}_{date_str}.zip"
    elif 1 < len(unique_folders) <= 3:
        zip_filename = f"{'_'.join(unique_folders)}_{date_str}.zip"
    else:
        zip_filename = f"DocxStacked_Folders_{date_str}.zip"

    return StreamingResponse(
        stream_zip_files(files_with_arcnames),
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
async def download_bundle_zip(
    job_id: Optional[str] = None,
    subject: Optional[str] = None,
    files: Optional[str] = Query(None, description="Comma-separated filenames or paths to include in the bundle"),
):
    """
    Download a zip bundle containing exported documents streamed in real-time with ZIP_STORED.
    If files param is provided, bundles only those files.
    If subject param is provided, bundles all files for that subject.
    If job_id is specified, bundles files for that job.
    """
    output_dir = settings.OUTPUT_DIR
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="No export files available to bundle")

    target_files: List[Path] = []

    if files:
        req_files = [f.strip() for f in files.split(",") if f.strip()]
        for fn in req_files:
            # find match in output_dir
            clean_fn = fn.replace("\\", "/").split("/")[-1]
            matches = list(output_dir.glob(f"*/{clean_fn}"))
            if matches:
                target_files.append(matches[0])
            else:
                p_cand = (settings.BASE_DIR / fn).resolve()
                if p_cand.exists() and p_cand.is_file() and p_cand.is_relative_to(output_dir.resolve()):
                    target_files.append(p_cand)
    elif subject:
        sub_dir = output_dir / subject
        if sub_dir.exists():
            target_files = [p for p in sub_dir.rglob("*") if p.is_file() and p.suffix.lower() in (".docx", ".zip", ".pdf", ".png", ".jpg", ".jpeg")]
    else:
        target_files = [p for p in output_dir.rglob("*") if p.is_file() and p.suffix.lower() in (".docx", ".zip", ".pdf", ".png", ".jpg", ".jpeg")]

    # Filter out test artifacts
    valid_targets: List[Path] = []
    for f in target_files:
        if f.stat().st_size < 50:
            continue
        f_u = f.name.upper()
        if "TEST" in f_u or "(EXTENSION INGESTED)" in f_u or f_u.endswith("TEST.DOCX"):
            continue
        valid_targets.append(f)

    if not valid_targets:
        if target_files:
            valid_targets = target_files
        else:
            raise HTTPException(status_code=404, detail="No exported files found to bundle")

    files_with_arcnames: List[Tuple[Path, str]] = []
    for f in valid_targets:
        rel_arcname = str(f.relative_to(output_dir)).replace("\\", "/")
        files_with_arcnames.append((f, rel_arcname))

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_filename = f"DocxStacked_Bundle_{subject or 'Selected'}_{date_str}.zip" if (subject or files) else f"DocxStacked_Bundle_{date_str}.zip"

    return StreamingResponse(
        stream_zip_files(files_with_arcnames),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{bundle_filename}"'},
    )


@router.get("/{exam_id:int}/download")
async def download_export_by_exam_id(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Download compiled .docx document by exam_id.
    Looks up the Exam record to locate the subject and filename in data/output.
    """
    from backend.app.db.models import Exam, Subject
    stmt = select(Exam).where(Exam.id == exam_id)
    res = await db.execute(stmt)
    exam = res.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy đề thi với ID={exam_id}")

    # Determine subject code
    subject = "EXAMS"
    if exam.subject_id:
        s_res = await db.execute(select(Subject).where(Subject.id == exam.subject_id))
        s_obj = s_res.scalar_one_or_none()
        if s_obj and s_obj.code:
            subject = s_obj.code.upper()

    title = exam.title.strip()
    if title.upper().startswith(f"{subject.upper()} -"):
        filename = f"{title}.docx"
    else:
        filename = f"{subject} - {title}.docx"

    # Search candidates in output directory
    out_dir = settings.STORAGE_DIR / "output"
    if not out_dir.exists() and hasattr(settings, "OUTPUT_DIR") and settings.OUTPUT_DIR.exists():
        out_dir = settings.OUTPUT_DIR
    sub_dir = out_dir / subject
    target_path = sub_dir / filename
    if not target_path.exists():
        # Fallback search by title
        candidates = list(sub_dir.glob(f"*{title}*.docx")) if sub_dir.exists() else []
        if candidates:
            target_path = candidates[0]
        else:
            # Fallback search across all output dirs
            all_cands = list(out_dir.rglob(f"*{title}*.docx")) if out_dir.exists() else []
            if all_cands:
                target_path = all_cands[0]
            else:
                raise HTTPException(status_code=404, detail=f"File Word cho đề thi '{exam.title}' chưa được tạo trên máy chủ.")

    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(
        path=str(target_path),
        filename=target_path.name,
        media_type=media_type,
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

        target_norm = target_str.replace("\\", "/").strip()
        if target_norm.startswith("data/output/"):
            rel_sub = target_norm[len("data/output/"):]
            resolved_path = (out_resolved / rel_sub).resolve()
        elif target_str.startswith("data/") or ".." in target_str or target_str.startswith("/"):
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


class ExportToFolderRequest(BaseModel):
    job_id: Optional[str] = None
    subject: Optional[str] = None
    exam_type: Optional[str] = None
    paths: Optional[List[str]] = None
    target_dir: Optional[str] = None  # Custom target directory path, e.g. Downloads/MLN122_FE


class ExportToFolderResponse(BaseModel):
    success: bool
    folder_path: str
    folder_name: str
    files_copied: int
    files: List[str]
    message: str


@router.post("/export-folder", response_model=ExportToFolderResponse)
async def export_files_to_named_folder(
    req: ExportToFolderRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Export Word documents directly into a real directory on disk named according to:
    {SUBJECT}_{CATEGORY} (e.g. MLN122_FE or MLN122_PE), without creating a zip file.
    FE and RE exams are grouped into {SUBJECT}_FE, and PE exams into {SUBJECT}_PE.
    Places the folder inside the user's Downloads directory (or specified target_dir).
    """
    import os
    import shutil

    output_dir = settings.OUTPUT_DIR
    target_files: List[Path] = []
    fallback_sub = req.subject or "EXAMS"
    fallback_cat = req.exam_type or "FE"

    if req.job_id:
        stmt = select(Job).where(Job.job_id == req.job_id)
        res = await db.execute(stmt)
        job = res.scalar_one_or_none()
        if job:
            if not req.subject:
                fallback_sub = job.subject_code or fallback_sub
            if not req.exam_type:
                fallback_cat = job.exam_type or fallback_cat
            job_files = (job.details or {}).get("files", [])
            for jf in job_files:
                p_str = jf.get("path")
                if p_str:
                    clean_p = p_str.replace("\\", "/").lstrip("/")
                    full_p = (settings.BASE_DIR / clean_p).resolve()
                    if full_p.exists() and full_p.is_file() and full_p.is_relative_to(output_dir.resolve()):
                        if full_p not in target_files:
                            target_files.append(full_p)

    if req.paths:
        for p_str in req.paths:
            clean_p = p_str.replace("\\", "/").lstrip("/")
            full_p = (settings.BASE_DIR / clean_p).resolve()
            if full_p.exists() and full_p.is_file() and full_p.is_relative_to(output_dir.resolve()):
                if full_p not in target_files:
                    target_files.append(full_p)

    if not target_files:
        if req.subject:
            sub_dir = output_dir / req.subject
            if sub_dir.exists():
                target_files = [p for p in sub_dir.glob("*.docx") if p.is_file()] + [p for p in sub_dir.glob("*.zip") if p.is_file()]
        else:
            target_files = [p for p in output_dir.rglob("*.docx") if p.is_file()]

    if not target_files:
        raise HTTPException(status_code=404, detail="Không tìm thấy file nào để xuất vào folder.")

    # Determine default destination root (Downloads directory)
    if req.target_dir:
        base_dest = Path(req.target_dir).resolve()
    else:
        downloads_path = Path.home() / "Downloads"
        base_dest = downloads_path if downloads_path.exists() else output_dir

    copied_files_list: List[str] = []
    dest_folders_set = set()

    for src_file in target_files:
        sub, cat = parse_subject_and_category(src_file.name, fallback_subject=fallback_sub, fallback_type=fallback_cat)
        folder_name = f"{sub}_{cat}"
        dest_folder = base_dest / folder_name
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_folders_set.add(dest_folder)

        dest_file = dest_folder / src_file.name
        try:
            shutil.copy2(src_file, dest_file)
            copied_files_list.append(src_file.name)
        except Exception as copy_err:
            logger.error(f"Failed to copy {src_file} to {dest_file}: {copy_err}")

    primary_folder = list(dest_folders_set)[0] if dest_folders_set else base_dest
    primary_name = primary_folder.name

    return ExportToFolderResponse(
        success=True,
        folder_path=str(primary_folder.resolve()),
        folder_name=primary_name,
        files_copied=len(copied_files_list),
        files=copied_files_list,
        message=f"Đã lưu thành công {len(copied_files_list)} file vào folder '{primary_name}' (tại {primary_folder})",
    )


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


@router.get("/fuexam/{filename}/download")
async def download_fuexam_file(filename: str):
    """Download compiled Word document for fuexam platform."""
    fuexam_dir = settings.BASE_DIR / "data" / "output" / "fuexam"
    clean_fn = filename if filename.endswith(".docx") else f"{filename}.docx"
    file_path = fuexam_dir / clean_fn
    if not file_path.exists():
        found = list(fuexam_dir.rglob(f"{clean_fn}")) or list(fuexam_dir.rglob(f"*{filename}*.docx"))
        if found:
            file_path = found[0]
        else:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy file {filename}")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

