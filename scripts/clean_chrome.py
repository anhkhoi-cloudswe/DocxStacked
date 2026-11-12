import subprocess
import json

cmd = ["powershell", "-Command", "Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | Select-Object ProcessId, ExecutablePath | ConvertTo-Json"]
res = subprocess.run(cmd, capture_output=True, text=True)
if res.stdout:
    try:
        data = json.loads(res.stdout)
        if isinstance(data, dict):
            data = [data]
        for p in data:
            exe = p.get("ExecutablePath") or ""
            if "ms-playwright" in exe.lower():
                pid = p["ProcessId"]
                print(f"Killing Playwright chrome: {pid}")
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    except Exception as e:
        print("Error parsing json:", e)
print("Done cleaning processes.")
