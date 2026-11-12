from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Optional
import zipfile
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/exports", tags=["exports"])


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
