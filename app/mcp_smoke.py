"""Smoke client for the in-process and stdio MCP transports."""

import argparse
import asyncio
import json
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from app.mcp_server import create_mcp_server


async def smoke(transport: str) -> dict:
    target = (
        create_mcp_server()
        if transport == "in-process"
        else StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"])
    )
    async with Client(target) as client:
        discovered = await client.list_tools()
        calls = {}
        for name, arguments in (
            ("get_erp_order", {"order_id": "SO-1001"}),
            ("get_logistics_status", {"shipment_id": "SHP-9001"}),
            ("get_shipment_note", {"shipment_id": "SHP-9001"}),
        ):
            result = await client.call_tool(name, arguments)
            calls[name] = result.structured_content
        return {"tools": [tool.name for tool in discovered.tools], "results": calls}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exercise all fixture-backed MCP tools")
    parser.add_argument("--transport", choices=("in-process", "stdio"), default="in-process")
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(smoke(args.transport)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
