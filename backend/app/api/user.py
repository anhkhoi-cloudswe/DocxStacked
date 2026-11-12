from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Exam, Job, JobStatus, Question, User
from backend.app.db.session import get_db

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/user", tags=["user"])


class DocumentItem(BaseModel):
    filename: str
    subject_code: str
    exam_title: str
    questions_count: int
    size_bytes: int
    size_formatted: str
    download_url: str
    created_at: Optional[str] = None
    is_cached: bool = True


class UserProfileResponse(BaseModel):
    logged_in: bool
    username: Optional[str] = None
    display_name: Optional[str] = None
    last_login_at: Optional[str] = None
    total_documents: int = 0
    total_subjects: int = 0


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(db: AsyncSession = Depends(get_db)):
    """Return profile of currently logged-in FUOverflow user."""
    from backend.app.api.auth import _get_current_logged_in_username

    username = _get_current_logged_in_username() or "Đông Khởi"
    res = await db.execute(select(User).where(User.username == username))
    user = res.scalar_one_or_none()

    # Scan output directory for total documents
    out_dir = settings.STORAGE_DIR / "output"
    total_docs = len(list(out_dir.glob("*/*.docx"))) if out_dir.exists() else 0
    subject_dirs = [d for d in out_dir.iterdir() if d.is_dir()] if out_dir.exists() else []

    return UserProfileResponse(
        logged_in=True if username else False,
        username=user.username if user else username,
        display_name=user.display_name if user else username,
        last_login_at=user.last_login_at.isoformat() if (user and user.last_login_at) else datetime.utcnow().isoformat(),
        total_documents=total_docs,
        total_subjects=len(subject_dirs),
    )


@router.get("/documents", response_model=List[DocumentItem])
async def get_my_documents(db: AsyncSession = Depends(get_db)):
    """
    List all generated Word documents for user review and 1-click download
    without re-crawling.
    """
    out_dir = settings.STORAGE_DIR / "output"
    if not out_dir.exists():
        return []

    # Map existing jobs with file info
    jobs_res = await db.execute(
        select(Job).where(Job.status == JobStatus.COMPLETED).order_by(Job.id.desc())
    )
    completed_jobs = jobs_res.scalars().all()

    file_metadata_map: Dict[str, Dict[str, Any]] = {}
    for j in completed_jobs:
        if j.details and isinstance(j.details, dict) and "files" in j.details:
            for f in j.details["files"]:
                fn = f.get("filename")
                if fn and fn not in file_metadata_map:
                    file_metadata_map[fn] = {
                        "exam_title": f.get("exam_title", fn.replace(".docx", "")),
                        "questions_count": f.get("questions_count", 0),
                        "created_at": j.created_at.strftime("%H:%M %d/%m/%Y") if j.created_at else None,
                    }

    documents: List[DocumentItem] = []
    # Scan all subject folders in output/
    for subj_dir in sorted(out_dir.iterdir()):
        if not subj_dir.is_dir():
            continue
        subj_code = subj_dir.name.upper()
        for doc_file in sorted(subj_dir.glob("*.docx"), key=lambda f: f.stat().st_mtime, reverse=True):
            fn = doc_file.name
            size_b = doc_file.stat().st_size
            meta = file_metadata_map.get(fn, {})
            exam_title = meta.get("exam_title") or fn.replace(".docx", "")
            q_count = meta.get("questions_count", 0)

            # If question count not in metadata, inspect exams in DB
            if q_count == 0:
                exam_res = await db.execute(
                    select(Exam).where(Exam.title.ilike(f"%{subj_code}%")).limit(1)
                )
                ex = exam_res.scalar_one_or_none()
                q_count = ex.question_count if ex else 60

            created_str = meta.get("created_at")
            if not created_str:
                created_dt = datetime.fromtimestamp(doc_file.stat().st_mtime)
                created_str = created_dt.strftime("%H:%M %d/%m/%Y")

            rel_path = f"data/output/{subj_code}/{fn}"
            download_url = f"/api/exports/download?file={rel_path}"

            documents.append(
                DocumentItem(
                    filename=fn,
                    subject_code=subj_code,
                    exam_title=exam_title,
                    questions_count=q_count or 60,
                    size_bytes=size_b,
                    size_formatted=_format_size(size_b),
                    download_url=download_url,
                    created_at=created_str,
                    is_cached=True,
                )
            )

    return documents


@router.delete("/documents")
async def delete_document(file: str = Query(..., description="File path or filename to delete")):
    """Delete an exported document safely, strictly restricted to output directory."""
    try:
        out_resolved = (settings.STORAGE_DIR / "output").resolve()
        target_str = file.replace("\\", "/")

        if target_str.startswith("data/") or ".." in target_str or target_str.startswith("/"):
            resolved = (settings.BASE_DIR / target_str.lstrip("/")).resolve()
        else:
            resolved = (out_resolved / file).resolve()

        # Verify it is strictly inside output directory
        try:
            is_inside = resolved.is_relative_to(out_resolved) and resolved != out_resolved
        except AttributeError:
            is_inside = str(resolved).startswith(str(out_resolved)) and resolved != out_resolved

        if not is_inside:
            logger.warning(f"Attempted delete outside output directory: {file}")
            raise HTTPException(status_code=403, detail="Access denied: file must be inside output directory")

        if not resolved.exists() or not resolved.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        resolved.unlink()
        # Also delete sidecar metadata if it exists
        meta_p = resolved.with_name(resolved.name + ".meta.json")
        if meta_p.exists():
            meta_p.unlink()

        logger.info(f"Deleted user document: {resolved}")
        return {"success": True, "message": f"Đã xóa thành công file {resolved.name}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        raise HTTPException(status_code=500, detail=str(e))
