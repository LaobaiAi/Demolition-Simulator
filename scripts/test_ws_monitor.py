"""Monitor WebSocket messages during pipeline execution."""
import asyncio
import json
import websockets

async def main():
    uri = "ws://localhost:8000/ws/chat"
    async with websockets.connect(uri) as ws:
        print("[WS] Connected")

        # Send launch_pipeline for quick_visual
        msg = {
            "type": "launch_pipeline",
            "pipeline": "visual_demolition",
            "params": {
                "mode": "topology",
                "strategy": "top_down",
                "effects_preset": "standard",
                "speed": 1.0,
                "structure_params": {"num_bays_x": 2, "num_stories": 3, "span_x_m": 6.0, "story_height_m": 3.0, "steel_grade": "Q355"},
            },
        }
        await ws.send(json.dumps(msg))
        print(f"[WS] Sent launch_pipeline")

        step_count = 0
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(raw)
                t = data.get("type", "?")

                if t == "ping":
                    continue

                if t == "pipeline_start":
                    print(f"[WS] pipeline_start: {data.get('pipeline')} total_steps={data.get('total_steps')} strategy={data.get('strategy')}")

                elif t == "pipeline_step":
                    step_count += 1
                    tool = data.get("tool", "?")
                    progress = data.get("progress", 0)
                    phase = data.get("phase", "?")
                    step_data = data.get("data", {})
                    error = data.get("error")

                    # Summarize data keys
                    if isinstance(step_data, dict):
                        keys = list(step_data.keys())
                        sizes = {}
                        for k in keys[:8]:
                            v = step_data[k]
                            if isinstance(v, list):
                                sizes[k] = f"[{len(v)}]"
                            elif isinstance(v, str):
                                sizes[k] = f"str({len(v)})"
                            else:
                                sizes[k] = type(v).__name__
                    else:
                        sizes = {}

                    print(f"[WS] pipeline_step [{step_count}] {tool}: {phase} progress={progress}")
                    if error:
                        print(f"     ERROR: {error[:200]}")
                    if sizes:
                        print(f"     data keys: {sizes}")
                    if step_data and "nodes" in step_data:
                        print(f"     HAS NODES: {len(step_data['nodes'])} nodes, {len(step_data.get('elements',[]))} elements")

                elif t == "pipeline_complete":
                    steps = data.get("timeline_steps", [])
                    print(f"[WS] pipeline_complete: timeline_steps={len(steps)} step_count={data.get('step_count')}")
                    if steps:
                        print(f"     First step: {steps[0]}")
                        print(f"     Last step: {steps[-1]}")
                        # Check element IDs
                        element_ids = [s.get("elementId") for s in steps]
                        print(f"     Element IDs: {element_ids}")
                    break

                elif t == "pipeline_error":
                    print(f"[WS] pipeline_error: {data.get('content', '?')}")
                    break

                else:
                    print(f"[WS] other: {t} — {json.dumps(data, ensure_ascii=False)[:200]}")

            except asyncio.TimeoutError:
                print("[WS] Timeout waiting for message")
                break
            except Exception as e:
                print(f"[WS] Error: {e}")
                break

        print(f"\n[WS] Total pipeline steps received: {step_count}")

asyncio.run(main())
