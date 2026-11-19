from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Exam, Job, JobStatus, Question, Subject, User
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
    seen_exam_keys: Set[str] = set()

    # Scan all subject folders in output/ and collect candidate docx files
    candidate_files = []
    for subj_dir in out_dir.iterdir():
        if not subj_dir.is_dir():
            continue
        subj_code = subj_dir.name.upper()
        # Hide test subject folders
        if "TEST" in subj_code or subj_code.startswith("T") and len(subj_code) == 6 and any(char.isdigit() for char in subj_code):
            continue

        for doc_file in subj_dir.glob("*.docx"):
            if not doc_file.is_file():
                continue
            fn_u = doc_file.name.upper()
            size_b = doc_file.stat().st_size

            # Filter rules:
            # 1. Hide 20 byte or < 50 byte files
            if size_b < 50:
                continue
            # 2. Hide test files (TEST101..., "MLN122 - Test", (Extension Ingested))
            if "TEST" in fn_u or "TEST" in subj_code or "(EXTENSION INGESTED)" in fn_u or fn_u.endswith("TEST.DOCX") or " - TEST" in fn_u:
                continue
            # 3. Hide files smaller than 50 KB
            if size_b < 50 * 1024:
                continue

            candidate_files.append((subj_code, doc_file, doc_file.stat().st_mtime, "FE", subj_dir.name))

        # Also scan {subj}_PE directory for PE exam folders
        pe_dir = subj_dir / f"{subj_code}_PE"
        if pe_dir.exists() and pe_dir.is_dir():
            for pe_exam_dir in pe_dir.iterdir():
                if pe_exam_dir.is_dir():
                    pe_files = [f for f in pe_exam_dir.iterdir() if f.is_file()]
                    if pe_files:
                        tot_size = sum(f.stat().st_size for f in pe_files)
                        latest_m = max(f.stat().st_mtime for f in pe_files)
                        candidate_files.append((subj_code, pe_exam_dir, latest_m, "PE", pe_exam_dir.name))

    # Sort strictly newest first across all subjects by real file modification time (mtime)
    candidate_files.sort(key=lambda x: x[2], reverse=True)

    for subj_code, target_item, mtime, item_type, title_name in candidate_files:
        if item_type == "PE":
            pe_files = [f for f in target_item.iterdir() if f.is_file()]
            tot_size = sum(f.stat().st_size for f in pe_files)
            created_dt = datetime.fromtimestamp(mtime)
            created_str = created_dt.strftime("%H:%M %d/%m/%Y")
            rel_folder = f"data/output/{subj_code}/{subj_code}_PE/{title_name}"
            # PE download bundles files or downloads folder
            download_url = f"/api/exports/bundle.zip?subject={subj_code}&files={','.join(str(f.relative_to(settings.BASE_DIR)).replace('\\\\', '/') for f in pe_files)}"
            documents.append(
                DocumentItem(
                    filename=f"{title_name} ({len(pe_files)} files)",
                    subject_code=subj_code,
                    exam_title=f"{title_name} [PE]",
                    questions_count=len(pe_files),
                    size_bytes=tot_size,
                    size_formatted=_format_size(tot_size),
                    download_url=download_url,
                    created_at=created_str,
                    is_cached=True,
                )
            )
            continue

        doc_file = target_item
        fn = doc_file.name
        size_b = doc_file.stat().st_size
        meta = file_metadata_map.get(fn, {})
        exam_title = meta.get("exam_title") or fn.replace(".docx", "")

        # Deduplicate by canonical exam key (e.g. normalize spaces and subject prefix)
        canonical_key = f"{subj_code}::{exam_title.strip().lower()}"
        if canonical_key in seen_exam_keys:
            continue
        seen_exam_keys.add(canonical_key)

        q_count = meta.get("questions_count", 0)

        # Load sidecar metadata if present
        meta_file = doc_file.parent / f"{doc_file.name}.meta.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as mf:
                    sidecar_meta = json.load(mf)
                    if sidecar_meta.get("questions_count"):
                        q_count = sidecar_meta["questions_count"]
                    if sidecar_meta.get("exam_title"):
                        exam_title = sidecar_meta["exam_title"]
            except Exception:
                pass

        # If question count not in metadata, query matching exam in DB or count in docx
        if q_count == 0:
            clean_fn = re.sub(r"[^a-zA-Z0-9]", "", fn.replace(".docx", "")).lower()
            exam_res = await db.execute(
                select(Exam).where(Exam.subject_id.in_(
                    select(Subject.id).where(Subject.code == subj_code)
                ))
            )
            for ex in exam_res.scalars().all():
                clean_t = re.sub(r"[^a-zA-Z0-9]", "", ex.title).lower()
                if clean_t and (clean_t in clean_fn or clean_fn in clean_t):
                    if ex.question_count and ex.question_count > 0:
                        q_count = ex.question_count
                        break
            if q_count == 0:
                try:
                    from docx import Document
                    doc = Document(str(doc_file))
                    q_count = sum(1 for p in doc.paragraphs if p.text.strip().startswith("Câu "))
                except Exception:
                    pass
        if q_count == 0:
            q_count = 50

        # Always use real file modification time (mtime)
        created_dt = datetime.fromtimestamp(mtime)
        created_str = created_dt.strftime("%H:%M %d/%m/%Y")

        rel_path = f"data/output/{subj_code}/{fn}"
        download_url = f"/api/exports/download?file={rel_path}"

        documents.append(
            DocumentItem(
                filename=fn,
                subject_code=subj_code,
                exam_title=exam_title,
                questions_count=q_count,
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
