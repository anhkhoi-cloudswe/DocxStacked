"""
scripts/run_real_fuexam_mln122_job.py
Executes MLN122 compilation strictly via POST /api/jobs and orchestrator.
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.db.session import init_db
from backend.app.modules.jobs.orchestrator import get_orchestrator


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


async def main():
    print("[1] Initializing DB...")
    await init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
        print("[2] Sending POST /api/jobs for MLN122 (threads 1473 & 1474)...")
        resp = await client.post("/api/jobs", json={
            "subject_code": "MLN122",
            "exam_type": "FE",
            "limit": 2,
            "platform": "fuexam",
            "exam_ids": [1473, 1474],
            "exam_titles": {
                "1473": "MLN122 - FA26 - FE - C1",
                "1474": "MLN122 - FA26 - FE - C2"
            }
        })
        if resp.status_code != 200:
            print(f"[ERROR] POST /api/jobs failed with HTTP {resp.status_code}: {resp.text}")
            return

        job_info = resp.json()
        job_id = job_info["job_id"]
        print(f"[3] Job created successfully: job_id={job_id}")

        orchestrator = get_orchestrator()
        task = orchestrator._running_tasks.get(job_id)
        if task:
            print("[4] Awaiting background orchestrator task...")
            await task
        else:
            print("[4] No running task found; checking status...")

        status_resp = await client.get(f"/api/jobs/{job_id}")
        status_data = status_resp.json()
        print(f"[5] Final Job Status: {status_data['status']}")
        if status_data["status"] == "failed":
            print(f"[ERROR] Job failed: {status_data.get('error_message')}")
            return

        files = status_data["details"].get("files", [])
        print(f"[6] Total files generated: {len(files)}")
        for f in files:
            p = Path(f["path"])
            if not p.is_absolute():
                p = Path(__file__).resolve().parent.parent / p
            sha = compute_sha256(p) if p.exists() else "N/A"
            meta_path = Path(str(p) + ".meta.json")
            meta_data = {}
            if meta_path.exists():
                meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
            print(f"--- File: {p.name} ---")
            print(f"  Path: {p}")
            print(f"  Size: {p.stat().st_size if p.exists() else 0} bytes")
            print(f"  SHA256: {sha}")
            print(f"  Thread ID: {meta_data.get('thread_id')}")
            print(f"  Term: {meta_data.get('term')}")
            print(f"  Questions: {meta_data.get('questions_count')}")
            print(f"  Breakdown: {meta_data.get('source_breakdown')}")
            print(f"  Updated at: {meta_data.get('updated_at')}")


if __name__ == "__main__":
    asyncio.run(main())
