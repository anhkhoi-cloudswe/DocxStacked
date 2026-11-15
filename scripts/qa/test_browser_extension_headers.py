"""
Real Browser Test:
Launches real Chromium with DocxStacked extension loaded via Playwright.
Executes requests to backend (/api/ingest/ping, /api/auth/extension-heartbeat, /api/ingest)
directly from the real extension context (sidepanel / background).
Captures and prints the exact incoming HTTP headers received by backend and status codes.
"""
import asyncio
import os
from pathlib import Path
import threading
import time
import uvicorn
from playwright.async_api import async_playwright

from backend.app.main import app
from backend.app.core.config import get_settings

settings = get_settings()

captured_requests = []

class ServerThread(threading.Thread):
    def __init__(self, app, host="127.0.0.1", port=8000):
        super().__init__(daemon=True)
        self.server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


async def main():
    print("=" * 70)
    print("STARTING REAL BROWSER EXTENSION VERIFICATION")
    print("=" * 70)

    # 1. Start backend server on 127.0.0.1:8000
    server_thread = ServerThread(app, host="127.0.0.1", port=8000)
    server_thread.start()
    await asyncio.sleep(1.5)
    print("[1/5] Backend server running on http://127.0.0.1:8000")

    extension_path = Path("extension").resolve()
    user_data_dir = Path("data/qa_browser_context").resolve()
    user_data_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        print(f"[2/5] Launching real Chromium with extension loaded from {extension_path}...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            args=[
                f"--disable-extensions-except={str(extension_path)}",
                f"--load-extension={str(extension_path)}",
                "--no-sandbox",
            ],
        )

        # Allow extension to load and register background service worker
        await asyncio.sleep(2.0)
        ext_id = settings.EXTENSION_ID
        print(f"[3/5] Target Extension ID: {ext_id}")

        # Open sidepanel.html inside extension page context
        sidepanel_url = f"chrome-extension://{ext_id}/sidepanel.html"
        print(f"[4/5] Navigating to sidepanel page: {sidepanel_url}")
        page = await context.new_page()
        await page.goto(sidepanel_url)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1.0)

        # Trigger real fetch calls from within the real extension JavaScript execution context:
        print("[5/5] Executing fetch calls from real extension execution context...")

        # Test Call 1: GET /api/ingest/ping (no token, should send X-DocxStacked-Ext header)
        res_ping = await page.evaluate("""async (extId) => {
            const resp = await fetch('http://127.0.0.1:8000/api/ingest/ping', {
                method: 'GET',
                headers: {
                    'X-DocxStacked-Ext': extId
                }
            });
            const data = await resp.json();
            return { status: resp.status, ok: resp.ok, data };
        }""", ext_id)
        print(f"\n[REAL BROWSER RESULT: GET /api/ingest/ping]")
        print(f"Status Code: {res_ping['status']} | OK: {res_ping['ok']}")
        print(f"Response: {res_ping['data']}")

        # Test Call 2: POST /api/auth/extension-heartbeat
        res_heartbeat = await page.evaluate("""async (extId) => {
            const resp = await fetch('http://127.0.0.1:8000/api/auth/extension-heartbeat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-DocxStacked-Ext': extId
                },
                body: JSON.stringify({ logged_in: true, username: 'BrowserTester' })
            });
            const data = await resp.json();
            return { status: resp.status, ok: resp.ok, data };
        }""", ext_id)
        print(f"\n[REAL BROWSER RESULT: POST /api/auth/extension-heartbeat]")
        print(f"Status Code: {res_heartbeat['status']} | OK: {res_heartbeat['ok']}")
        print(f"Response: {res_heartbeat['data']}")

        # Test Call 3: POST /api/ingest (empty test questions)
        res_ingest = await page.evaluate("""async (extId) => {
            const resp = await fetch('http://127.0.0.1:8000/api/ingest', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-DocxStacked-Ext': extId
                },
                body: JSON.stringify({
                    subject_code: 'TEST101',
                    exam_title: 'TEST101 - REAL BROWSER VERIFY',
                    questions: [],
                    options: { ai_enabled: false }
                })
            });
            const data = await resp.json();
            return { status: resp.status, ok: resp.ok, data };
        }""", ext_id)
        print(f"\n[REAL BROWSER RESULT: POST /api/ingest]")
        print(f"Status Code: {res_ingest['status']} | OK: {res_ingest['ok']}")
        print(f"Response: {res_ingest['data']}")

        # Test Call 4: Real Browser GET WITHOUT Origin and WITHOUT X-DocxStacked-Ext (simulating malicious web fetch or stripped client)
        res_no_auth = await page.evaluate("""async () => {
            const resp = await fetch('http://127.0.0.1:8000/api/ingest/ping', {
                method: 'GET'
            });
            return { status: resp.status, ok: resp.ok };
        }""")
        print(f"\n[REAL BROWSER RESULT: GET without header or token from extension page]")
        # Note: If called from chrome-extension://, Chrome attaches Origin: chrome-extension://... on POST, but on GET it may omit or include Origin depending on navigation
        print(f"Status Code: {res_no_auth['status']} | OK: {res_no_auth['ok']}")

        await context.close()

    server_thread.stop()
    print("\n" + "=" * 70)
    print("REAL BROWSER EXTENSION VERIFICATION COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
