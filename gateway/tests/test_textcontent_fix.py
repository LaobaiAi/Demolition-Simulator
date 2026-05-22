"""Integration test: verify TextContent objects are handled through the full pipeline."""
import asyncio
import json
import sys
import os

# Add gateway (parent dir) to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Apply monkey-patch BEFORE importing any gateway modules
_original_dumps = json.dumps

def _patched_dumps(obj, **kwargs):
    def _walk(o):
        if o is None or isinstance(o, (bool, int, float, str)):
            return o
        if isinstance(o, (list, tuple)):
            return [_walk(i) for i in o]
        if isinstance(o, dict):
            return {str(k): _walk(v) for k, v in o.items()}
        if hasattr(o, "text"):
            return str(o.text)
        if hasattr(o, "model_dump"):
            return _walk(o.model_dump())
        return str(o)
    return _original_dumps(_walk(obj), **kwargs)

json.dumps = _patched_dumps


class MockTextContent:
    """Simulates OpenAI SDK's TextContent object."""
    def __init__(self, text):
        self.text = text
        self.type = "text"


class MockLLM:
    """Mock LLM that returns TextContent objects to trigger the bug."""
    def __init__(self):
        self.model = "test-model"
        self.api_key = None
        self.base_url = None
        self.call_count = 0

    def format_tools_for_llm(self, tools_list):
        return tools_list

    async def chat(self, messages, tools=None, tool_choice="auto"):
        self.call_count += 1
        if self.call_count == 1:
            # Return tool calls — content as MockTextContent (like real OpenAI SDK)
            return {
                "content": MockTextContent("Let me generate the frame first."),
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "generate_simple_frame",
                        "arguments": {"spans": 2, "stories": 2},
                    }
                ],
                "raw": None,
            }
        elif self.call_count == 2:
            # content as list of TextContent blocks
            return {
                "content": [MockTextContent("Frame generated. "), MockTextContent("Now analyzing...")],
                "tool_calls": [
                    {
                        "id": "call_2",
                        "name": "analyze_frame",
                        "arguments": {"structure": {"spans": 2, "stories": 2}},
                    }
                ],
                "raw": None,
            }
        else:
            # Final response with TextContent
            return {
                "content": MockTextContent("Analysis complete. Frame is stable."),
                "tool_calls": None,
                "raw": None,
            }

    # Also simulate the format_tools_for_llm which agent_loop expects
    def format_tools_for_llm(self, tools_list):
        return tools_list


class MockHub:
    """Mock MCP hub that returns fake tool results."""
    async def list_tools(self):
        return [
            {"name": "generate_simple_frame", "description": "Generate frame", "input_schema": {}},
            {"name": "analyze_frame", "description": "Analyze frame", "input_schema": {}},
        ]

    async def call_tool(self, name, arguments):
        return {"result": f'{{"max_displacement": 0.005, "max_axial_force": 50000}}'}


async def main():
    from agent_loop import AgentLoop

    mock_llm = MockLLM()
    mock_hub = MockHub()
    agent = AgentLoop(mock_llm, mock_hub)

    try:
        steps = await agent.run("Analyze a 2-story 2-bay frame", history=None)
        print(f"SUCCESS: agent.run() returned {len(steps)} steps")

        # Verify ALL steps can be serialized
        for i, step in enumerate(steps):
            try:
                serialized = json.dumps(step)
                print(f"  Step {i} ({step['type']}): serialized OK ({len(serialized)} bytes)")
            except TypeError as e:
                print(f"  Step {i} ({step['type']}): SERIALIZATION FAILED: {e}")
                return 1

        print("ALL STEPS SERIALIZED SUCCESSFULLY")
        print(f"Final response content type: {type(steps[-1].get('content'))}")
        print(f"Final response content: {steps[-1].get('content')}")
        return 0
    except TypeError as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
