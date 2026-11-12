import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Determine project root by locating the directory containing both backend and frontend
script_dir = Path(__file__).resolve().parent
if (script_dir / "backend").exists() and (script_dir / "frontend").exists():
    PROJECT_ROOT = script_dir
elif (script_dir.parent / "backend").exists() and (script_dir.parent / "frontend").exists():
    PROJECT_ROOT = script_dir.parent
elif (script_dir.parent.parent / "backend").exists() and (script_dir.parent.parent / "frontend").exists():
    PROJECT_ROOT = script_dir.parent.parent
else:
    PROJECT_ROOT = Path("C:/AK/PET_PROJECTS/DocxStacked").resolve()

VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON_EXE = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

def main():
    print("\n" + "=" * 60)
    print("   DOCXSTACKED - KHOI CHAY DONG THOI BACKEND & FRONTEND")
    print("=" * 60)

    # 1. Start Backend FastAPI
    print("\n[1/2] Dang khoi dong Backend FastAPI tai http://127.0.0.1:8000...")
    backend_cmd = [
        PYTHON_EXE,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--reload",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    backend_proc = subprocess.Popen(
        backend_cmd,
        cwd=str(PROJECT_ROOT),
    )

    # 2. Start Frontend Vite
    print("[2/2] Dang khoi dong Frontend React Vite tai http://localhost:5173...")
    npm_cmd = ["cmd.exe", "/c", "npm", "--prefix", "frontend", "run", "dev"] if os.name == "nt" else ["npm", "--prefix", "frontend", "run", "dev"]
    frontend_proc = subprocess.Popen(
        npm_cmd,
        cwd=str(PROJECT_ROOT),
    )

    time.sleep(2)
    print("\n" + "-" * 60)
    print(">> He thong da san sang!")
    print(">> Giao dien Web UI  : http://localhost:5173")
    print(">> API Docs (Swagger): http://localhost:8000/docs")
    print("-" * 60)
    print("Nhan Ctrl + C de dung toan bo ung dung.\n")

    try:
        while True:
            time.sleep(1)
            if backend_proc.poll() is not None:
                print("\n[!] Backend da dung dot ngot.")
                break
            if frontend_proc.poll() is not None:
                print("\n[!] Frontend da dung dot ngot.")
                break
    except KeyboardInterrupt:
        print("\nDang dung he thong...")
    finally:
        for p, name in [(backend_proc, "Backend"), (frontend_proc, "Frontend")]:
            if p and p.poll() is None:
                try:
                    if os.name == "nt":
                        subprocess.call(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        p.terminate()
                except Exception:
                    pass
        print("Da dung toan bo ung dung.")

if __name__ == "__main__":
    main()

