"""Debug script — inject JS to read React state and WebSocket messages."""
from playwright.sync_api import sync_playwright

def log(msg):
    print(f"[TEST] {msg}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})

    all_console = []
    page.on("console", lambda msg: all_console.append(f"[{msg.type}] {msg.text}"))

    # Intercept WebSocket messages
    ws_received = []
    page.evaluate("""
        window.__wsMessages = [];
        const origSend = WebSocket.prototype.send;
        WebSocket.prototype.send = function(data) {
            window.__wsMessages.push({dir: 'send', data: data});
            return origSend.call(this, data);
        };
    """)

    page.goto("http://localhost:3000")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    # Open dialog and launch
    demo_btn = page.locator("button", has_text="Demo Library")
    demo_btn.click()
    page.wait_for_timeout(1000)

    cards = page.locator("[role='dialog'] .rounded-xl").all()
    for c in cards:
        if "Quick Visual" in c.inner_text():
            c.locator("button", has_text="Run").click()
            log("Launched Quick Visual")
            break

    # Wait for pipeline
    page.wait_for_timeout(10000)

    # Try to check React fiber for frameStructure state
    state_info = page.evaluate("""
        // Try to find React root and state
        const rootEl = document.getElementById('__next');
        if (!rootEl) return 'no __next element';

        const fiberKey = Object.keys(rootEl).find(k => k.startsWith('__reactFiber'));
        if (!fiberKey) return 'no react fiber';

        let fiber = rootEl[fiberKey];
        let depth = 0;
        let found = [];

        // Walk fiber tree looking for state with nodes/elements
        function walk(f, d) {
            if (!f || d > 100) return;
            if (f.memoizedState) {
                let state = f.memoizedState;
                while (state) {
                    const val = state.queue?.lastRenderedState;
                    if (val && typeof val === 'object' && val.nodes && val.elements) {
                        found.push({
                            depth: d,
                            nodeCount: val.nodes?.length,
                            elemCount: val.elements?.length,
                            hasNodes: !!val.nodes,
                            hasElements: !!val.elements,
                        });
                    }
                    state = state.next;
                }
            }
            walk(f.child, d + 1);
            walk(f.sibling, d);
        }
        walk(fiber, 0);
        return found.length > 0 ? found : 'no frameStructure found in fiber tree';
    """)
    log(f"React state check: {state_info}")

    # Check DOM for structure-related elements
    body_text = page.locator("body").inner_text()
    log("=== BODY TEXT (filtered) ===")
    for line in body_text.split('\n'):
        line = line.strip()
        if line and len(line) > 2 and not line.startswith('<'):
            lower = line.lower()
            if any(w in lower for w in ['structure', 'frame', 'element', 'node', 'pipeline', 'complete', 'launched', 'demolition', 'generated', 'collapse', 'standing', 'error', 'failed', 'send']):
                log(f"  {line[:200]}")

    # Check all console messages
    log("=== ALL CONSOLE (last 20) ===")
    for m in all_console[-20:]:
        log(f"  {m[:300]}")

    # Check WS messages sent
    ws_sent = page.evaluate("window.__wsMessages || []")
    log(f"WS messages sent: {len(ws_sent)}")
    for m in ws_sent:
        log(f"  {str(m)[:200]}")

    page.screenshot(path="E:/Claude code workspace/XuanwuAI Demolition Simulator/test_screenshots/debug_final.png", full_page=True)

    browser.close()
    log("Done")
