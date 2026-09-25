"""Standalone read-only MCP server backed by the enterprise tool service."""

import argparse
from contextlib import asynccontextmanager

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from app.connectors import ConnectorBundle, EnterpriseToolService, create_connector_bundle
from app.connectors.models import ERPOrder, ShipmentNote, ShipmentStatus
from app.errors import ResolutionError

READ_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)


def _safe_call(function, record_id):
    try:
        return function(record_id)
    except ResolutionError as exc:
        raise ToolError(f"{exc.code}: {exc.message}") from None
    except Exception:
        raise ToolError("connector_failure: The connector call could not be completed.") from None


def create_mcp_server(tool_service: EnterpriseToolService | None = None) -> MCPServer:
    bundle = ConnectorBundle(tool_service) if tool_service is not None else create_connector_bundle()

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield {"tools": bundle.tools}
        finally:
            bundle.close()

    server = MCPServer(
        name="supply-chain-enterprise-tools",
        title="Supply Chain Enterprise Tools",
        description="Read-only ERP and logistics records used by the exception resolver.",
        version="0.4.0",
        lifespan=lifespan,
    )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def get_erp_order(order_id: str) -> ERPOrder:
        """Get one ERP order by its exact order identifier."""
        return _safe_call(bundle.tools.get_erp_order, order_id)

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def get_logistics_status(shipment_id: str) -> ShipmentStatus:
        """Get the current logistics status for one shipment."""
        return _safe_call(bundle.tools.get_logistics_status, shipment_id)

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def get_shipment_note(shipment_id: str) -> ShipmentNote:
        """Get the carrier note associated with one shipment."""
        return _safe_call(bundle.tools.get_shipment_note, shipment_id)

    return server


def validate_http_bind(host: str) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("v0.4 MCP HTTP transport is restricted to a loopback address")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the read-only enterprise MCP server")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)
    server = create_mcp_server()
    if args.transport == "stdio":
        server.run("stdio")
    else:
        validate_http_bind(args.host)
        server.run("streamable-http", host=args.host, port=args.port, streamable_http_path="/mcp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
