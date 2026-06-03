"""Test full frontend visual demolition flow v3."""
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = "E:/Claude code workspace/XuanwuAI Demolition Simulator/test_screenshots"

def log(msg):
    print(f"[TEST] {msg}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})

    ws_msgs = []
    page.on("console", lambda msg: ws_msgs.append(msg.text) if "pipeline" in msg.text.lower() or "error" in msg.text.lower() else None)

    page.goto("http://localhost:3000")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
    log("Page loaded")
    page.screenshot(path=f"{SCREENSHOT_DIR}/f01_loaded.png", full_page=True)

    # Open Demo Library
    demo_btn = page.locator("button", has_text="Demo Library")
    demo_btn.click()
    page.wait_for_timeout(1500)
    log("Demo Library opened")
    page.screenshot(path=f"{SCREENSHOT_DIR}/f02_demo_dialog.png", full_page=True)

    # Find Quick Visual card and click Run
    cards = page.locator("[role='dialog'] .rounded-xl").all()
    log(f"Found {len(cards)} cards in dialog")

    quick_card = None
    for c in cards:
        if "Quick Visual" in c.inner_text():
            quick_card = c
            break

    if quick_card:
        run_btn = quick_card.locator("button", has_text="Run")
        run_btn.click()
        log("Clicked Run on Quick Visual")
        page.wait_for_timeout(2000)

        # Watch for pipeline progress and animation
        for i in range(25):
            page.wait_for_timeout(1000)
            page.screenshot(path=f"{SCREENSHOT_DIR}/f03_frame_{i:02d}.png", full_page=True)

            # Check page body for status
            body = page.locator("body").inner_text()
            indicators = ["Generating", "Planning", "Creating", "Configuring", "complete", "collapsed", "standing", "Pipeline launched"]
            found = [ind for ind in indicators if ind.lower() in body.lower()]
            if found:
                log(f"  [{i+1}s] Indicators: {found}")

            # Check if canvas has content (structure rendered)
            canvas = page.locator("canvas").first
            if canvas.is_visible():
                # Check for any visible 3D content
                pass

            # Check if animation is playing (look for collapsed/standing text)
            if "collapsed" in body.lower() or "standing" in body.lower():
                log(f"  [{i+1}s] Animation state detected!")
                break

        page.screenshot(path=f"{SCREENSHOT_DIR}/f04_final.png", full_page=True)

        # Dump key state
        log("Final body excerpt:")
        body = page.locator("body").inner_text()
        for line in body.split('\n'):
            line = line.strip()
            if line and len(line) > 3:
                # Print lines that seem relevant
                lower = line.lower()
                if any(w in lower for w in ['pipeline', 'structure', 'collapse', 'element', 'standing', 'animation', 'demolition', 'generated', 'complete', 'error']):
                    log(f"  {line[:150]}")
    else:
        log("ERROR: Quick Visual card not found!")

    log("Pipeline related console messages:")
    for m in ws_msgs[-10:]:
        log(f"  {m[:200]}")

    browser.close()
    log("Done")
