"""Check frontend console for errors during pipeline execution."""
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = "E:/Claude code workspace/XuanwuAI Demolition Simulator/test_screenshots"

def log(msg):
    print(f"[TEST] {msg}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})

    all_console = []
    page.on("console", lambda msg: all_console.append(f"[{msg.type}] {msg.text}"))

    page.goto("http://localhost:3000")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
    log("Page loaded")

    # Open and launch quick visual
    demo_btn = page.locator("button", has_text="Demo Library")
    demo_btn.click()
    page.wait_for_timeout(1000)

    cards = page.locator("[role='dialog'] .rounded-xl").all()
    for c in cards:
        if "Quick Visual" in c.inner_text():
            c.locator("button", has_text="Run").click()
            log("Launched Quick Visual")
            break

    # Wait for pipeline (longer)
    for i in range(15):
        page.wait_for_timeout(1000)
        page.screenshot(path=f"{SCREENSHOT_DIR}/step_{i:02d}.png", full_page=True)

    page.wait_for_timeout(5000)
    page.screenshot(path=f"{SCREENSHOT_DIR}/final_state.png", full_page=True)

    # Dump ALL console messages
    log("=== ALL CONSOLE MESSAGES ===")
    for m in all_console:
        if len(m) > 300:
            m = m[:300] + "..."
        log(f"  {m}")

    # Check React state via JS eval
    log("=== BODY TEXT ===")
    body = page.locator("body").inner_text()
    for line in body.split('\n'):
        line = line.strip()
        if line and len(line) > 3:
            lower = line.lower()
            if any(w in lower for w in ['pipeline', 'structure', 'collapse', 'element', 'standing', 'animation', 'demolition', 'generated', 'complete', 'error', 'frame', 'node']):
                log(f"  {line[:200]}")

    browser.close()
    log("Done")
