"""Agnes AI Video Generation CAIAO Server."""

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from scene_prompts import SCENE_PROMPTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agnes-video-server")

server = Server("agnes-video-server")

API_BASE = "https://apihub.agnes-ai.com/v1"
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_key.txt")


def _load_api_key() -> str:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return f.read().strip()
    return os.environ.get("AGNES_API_KEY", "")


def _save_api_key(key: str):
    with open(CONFIG_FILE, "w") as f:
        f.write(key.strip())


def _call_agnes_api(method: str, endpoint: str, data: dict | None, api_key: str) -> dict:
    url = f"{API_BASE}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        logger.error(f"Agnes API error {e.code}: {error_body}")
        return {"error": f"HTTP {e.code}", "detail": error_body}
    except Exception as e:
        logger.error(f"Agnes API request failed: {e}")
        return {"error": str(e)}


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="generate_video",
            description="Create an AI video from reference frames via Agnes API. Returns a task ID for polling.",
            inputSchema={
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "api_key": {"type": "string", "description": "Agnes AI API key. Falls back to saved key or AGNES_API_KEY env var."},
                    "prompt": {"type": "string", "description": "Video scene description prompt"},
                    "image_urls": {"type": "array", "items": {"type": "string"}, "description": "Publicly accessible image URLs for Image-to-Video input"},
                    "width": {"type": "integer", "description": "Video width (must be divisible by 64)", "default": 1152},
                    "height": {"type": "integer", "description": "Video height (must be divisible by 64)", "default": 768},
                    "num_frames": {"type": "integer", "description": "Total frames (8n+1 format). 121 ≈ 5s at 24fps", "default": 121},
                    "frame_rate": {"type": "integer", "description": "Frames per second", "default": 24},
                    "seed": {"type": "integer", "description": "Random seed for reproducibility"},
                },
            },
        ),
        Tool(
            name="check_video_status",
            description="Poll Agnes API for video generation progress.",
            inputSchema={
                "type": "object",
                "required": ["task_id"],
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID from generate_video"},
                    "api_key": {"type": "string", "description": "API key if not saved"},
                },
            },
        ),
        Tool(
            name="generate_image",
            description="Generate or transform an image via Agnes Image 2.1 Flash. Supports text-to-image and image-to-image.",
            inputSchema={
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "api_key": {"type": "string", "description": "Agnes AI API key. Falls back to saved key or AGNES_API_KEY env var."},
                    "prompt": {"type": "string", "description": "Image description or transformation prompt"},
                    "image": {"type": "string", "description": "Data URI base64 of input image for img2img (e.g. data:image/png;base64,...)"},
                    "size": {"type": "string", "description": "Output size like '1024x768' or '768x1024'", "default": "1024x768"},
                    "response_format": {"type": "string", "enum": ["url", "b64_json"], "description": "Output format: public URL or base64 JSON", "default": "url"},
                },
            },
        ),
        Tool(
            name="save_api_key",
            description="Save Agnes AI API key for reuse across calls.",
            inputSchema={
                "type": "object",
                "required": ["api_key"],
                "properties": {"api_key": {"type": "string", "description": "Agnes AI API key"}},
            },
        ),
        Tool(
            name="list_scene_prompts",
            description="List built-in cinematic demolition scene prompt templates.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info(f"Tool called: {name}")

    if name == "generate_video":
        prompt = arguments.get("prompt", "")
        api_key = arguments.get("api_key", "") or _load_api_key()
        if not api_key:
            return [TextContent(type="text", text=json.dumps({"error": "No API key configured. Use save_api_key or set AGNES_API_KEY env var."}))]

        payload = {
            "model": "agnes-video-v2.0",
            "prompt": prompt,
            "width": arguments.get("width", 1152),
            "height": arguments.get("height", 768),
            "num_frames": arguments.get("num_frames", 121),
            "frame_rate": arguments.get("frame_rate", 24),
        }
        image_urls = arguments.get("image_urls", [])
        if image_urls:
            payload["image"] = image_urls[0]
            if len(image_urls) > 1:
                payload["extra_body"] = {"image": image_urls, "mode": "keyframes"}
        if "seed" in arguments:
            payload["seed"] = arguments["seed"]

        result = _call_agnes_api("POST", "videos", payload, api_key)
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "check_video_status":
        task_id = arguments.get("task_id", "")
        api_key = arguments.get("api_key", "") or _load_api_key()
        if not api_key:
            return [TextContent(type="text", text=json.dumps({"error": "No API key configured"}))]
        result = _call_agnes_api("GET", f"videos/{task_id}", None, api_key)
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "generate_image":
        prompt = arguments.get("prompt", "")
        api_key = arguments.get("api_key", "") or _load_api_key()
        if not api_key:
            return [TextContent(type="text", text=json.dumps({"error": "No API key configured. Use save_api_key or set AGNES_API_KEY env var."}))]

        payload = {
            "model": "agnes-image-2.1-flash",
            "prompt": prompt,
            "size": arguments.get("size", "1024x768"),
        }
        image = arguments.get("image", "")
        extra_body = {}
        if image:
            extra_body["image"] = [image]
        response_format = arguments.get("response_format", "url")
        extra_body["response_format"] = response_format
        payload["extra_body"] = extra_body

        result = _call_agnes_api("POST", "images/generations", payload, api_key)
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "save_api_key":
        _save_api_key(arguments.get("api_key", ""))
        return [TextContent(type="text", text=json.dumps({"status": "ok"}))]

    elif name == "list_scene_prompts":
        return [TextContent(type="text", text=json.dumps(SCENE_PROMPTS))]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
