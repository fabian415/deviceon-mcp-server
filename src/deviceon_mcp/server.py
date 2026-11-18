"""Entry point: build the FastMCP app and run it over stdio or streamable HTTP."""

from __future__ import annotations

import argparse
import logging
import sys

from mcp.server.fastmcp import FastMCP

from .client import DeviceOnClient
from .config import Settings
from .confirm_store import ConfirmStore
from .deps import Deps
from .tools import register_toolsets

INSTRUCTIONS = """\
Tools for diagnosing devices managed by DeviceOn.
Typical flow: list_devices -> analyze_metric_periodicity -> capture_top_processes
-> request_kill_process -> (ask the user) -> confirm_kill_process.
Never call confirm_kill_process without the user's explicit approval in this conversation.
"""


def build_app(settings: Settings, host: str = "127.0.0.1", port: int = 8765) -> tuple[FastMCP, Deps]:
    deps = Deps(
        settings=settings,
        client=DeviceOnClient(settings),
        confirm=ConfirmStore(settings.confirm_ttl_sec),
    )
    mcp = FastMCP("deviceon", instructions=INSTRUCTIONS, host=host, port=port)
    enabled = register_toolsets(mcp, deps, settings.toolsets)
    logging.getLogger("deviceon_mcp").info("toolsets enabled: %s", ", ".join(enabled))
    return mcp, deps


def main() -> None:
    parser = argparse.ArgumentParser(description="DeviceOn MCP Server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    # stdout carries the MCP protocol on stdio; all logs must go to stderr.
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    mcp, _ = build_app(Settings.from_env(), args.host, args.port)
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
