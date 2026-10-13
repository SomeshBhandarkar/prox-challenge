"""Connection test: ask Claude one question and let it call our duty-cycle lookup.

Costs well under a cent. The API key is read from .env and is never printed.
Run from the project folder:  .venv/bin/python -m scripts.hello_agent
"""
import asyncio
import json
import os
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)
from dotenv import load_dotenv

from app.tools.data import get_duty_cycle

load_dotenv()
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ANTHROPIC_API_KEY is missing. Copy .env.example to .env and paste your key.")


@tool(
    "duty_cycle",
    "Look up the exact duty cycle from the manual's data.",
    {"process": str, "voltage": int, "amps": float},
)
async def duty_cycle_tool(args):
    result = get_duty_cycle(args["process"], args["voltage"], args["amps"])
    return {"content": [{"type": "text", "text": json.dumps(result)}]}


server = create_sdk_mcp_server(name="welder", version="1.0.0", tools=[duty_cycle_tool])

SYSTEM_PROMPT = (
    "You are an expert on the Vulcan OmniPro 220 welder. For any duty-cycle question, "
    "call the duty_cycle tool and use ONLY the numbers it returns. Answer in two short sentences."
)


async def main():
    options = ClaudeAgentOptions(
        model="claude-haiku-5-5",
        system_prompt=SYSTEM_PROMPT,
        tools=[],  # no built-in tools (no files, no shell)
        mcp_servers={"welder": server},
        allowed_tools=["mcp__welder__duty_cycle"],
        setting_sources=[],  # ignore any local Claude settings
        effort="low",
        max_turns=3,
        max_budget_usd=0.05,
    )
    question = "What's the duty cycle for MIG welding at 200A on 240V?"
    print(f"[question] {question}\n")
    async for message in query(prompt=question, options=options):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            print("[tools Claude can see]", message.data.get("tools"))
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    print(f"[tool call] {block.name} with {block.input}")
                elif isinstance(block, TextBlock):
                    print(f"[claude says] {block.text}")
        elif isinstance(message, ResultMessage):
            u = message.usage or {}
            print(f"\n[done] cost ${message.total_cost_usd:.4f} | turns {message.num_turns} | error: {message.is_error}")
            print(
                f"[tokens] input {u.get('input_tokens')} | output {u.get('output_tokens')} | "
                f"cache read {u.get('cache_read_input_tokens')} | cache written {u.get('cache_creation_input_tokens')}"
            )


asyncio.run(main())
