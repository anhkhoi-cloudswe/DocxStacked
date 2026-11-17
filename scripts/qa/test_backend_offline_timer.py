import asyncio
import os
import sys
import time
from playwright.async_api import async_playwright

EXT_PATH = os.path.abspath("extension")
USER_DATA_DIR = os.path.abspath("temp_ext_user_data_b")

async def test_backend_detection():
    print("=== TESTING BACKEND ONLINE -> OFFLINE -> ONLINE DETECTION ===")
    
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            args=[
                f"--disable-extensions-except={EXT_PATH}",
                f"--load-extension={EXT_PATH}",
            ]
        )
        
        await asyncio.sleep(2)
        
        ext_id = None
        for bg in context.service_workers:
            if "chrome-extension://" in bg.url:
                ext_id = bg.url.split("/")[2]
                break
        if not ext_id:
            ext_id = "kicplcdfmbcfjildbbimpfiljlmfokea"
            
        print(f"Extension ID: {ext_id}")
        page = await context.new_page()
        sidepanel_url = f"chrome-extension://{ext_id}/sidepanel.html"
        await page.goto(sidepanel_url)
        
        # 1. Verify Online initially
        await page.wait_for_selector("#backend-status", timeout=5000)
        status_text = await page.inner_text("#backend-status")
        print(f"Initial status: {status_text}")
        assert "Online" in status_text, f"Expected Online, got {status_text}"
        
        # 2. Inform orchestrator to kill backend
        print("READY_FOR_OFFLINE", flush=True)
        
        # Wait for orchestrator signal
        line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
        
        # Measure time until status is Offline
        t0 = time.time()
        print("Waiting for Offline status...")
        while True:
            text = await page.inner_text("#backend-status")
            if "Offline" in text:
                t_offline = time.time() - t0
                print(f"RESULT: Status changed to Offline in {t_offline:.2f} seconds!")
                break
            await asyncio.sleep(0.1)
            if time.time() - t0 > 15:
                print("TIMEOUT waiting for Offline")
                break
                
        # 3. Inform orchestrator to restart backend
        print("READY_FOR_ONLINE", flush=True)
        line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
        
        t1 = time.time()
        print("Waiting for Online status...")
        while True:
            text = await page.inner_text("#backend-status")
            if "Online" in text:
                t_online = time.time() - t1
                print(f"RESULT: Status changed to Online in {t_online:.2f} seconds!")
                break
            await asyncio.sleep(0.1)
            if time.time() - t1 > 15:
                print("TIMEOUT waiting for Online")
                break

        await context.close()

if __name__ == "__main__":
    asyncio.run(test_backend_detection())
