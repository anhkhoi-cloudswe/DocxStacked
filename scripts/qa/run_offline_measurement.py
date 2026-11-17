import subprocess
import time
import sys
import os

def run_test():
    proc = subprocess.Popen(
        [sys.executable, "scripts/qa/test_backend_offline_timer.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    backend_proc = None

    while True:
        line = proc.stdout.readline()
        if not line:
            break
        print(line, end="")
        if "READY_FOR_OFFLINE" in line:
            print(">>> Killing all uvicorn processes...")
            # Use taskkill on uvicorn / python processes running uvicorn
            os.system('powershell -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"')
            time.sleep(0.5)
            # Signal script that backend was killed
            proc.stdin.write("killed\n")
            proc.stdin.flush()
        elif "READY_FOR_ONLINE" in line:
            print(">>> Restarting backend on port 8000...")
            backend_proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"]
            )
            # Signal script that backend has been started
            proc.stdin.write("started\n")
            proc.stdin.flush()
            
    proc.wait()

if __name__ == "__main__":
    run_test()
